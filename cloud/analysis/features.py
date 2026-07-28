from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from math import sqrt
from typing import Any

import numpy as np

from cloud.analysis.feature_parameters import FeatureParameters
from cloud.analysis.coordinates import board_to_subject_coordinates
from cloud.analysis.physical_input import PhysicalPressureSession
from cloud.analysis.protocol_context import (
    StageId,
    StaticBalanceProtocolContext,
    validate_static_balance_protocol_context,
)
from cloud.analysis.models import FeatureSet, RawSession


SENSOR_ROWS = 48
SENSOR_COLUMNS = 64
SENSOR_POINTS = SENSOR_ROWS * SENSOR_COLUMNS


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class FeaturePipeline:
    def __init__(self, pipeline_version: str) -> None:
        if not pipeline_version.strip():
            raise ValueError("pipeline_version is required")
        self.pipeline_version = pipeline_version

    def extract(
        self,
        raw_session: RawSession,
        parameters: Mapping[str, Any],
    ) -> FeatureSet:
        parameter_snapshot = dict(parameters)
        parameters_sha256 = _canonical_sha256(parameter_snapshot)
        context = raw_session.context
        cache_key = _canonical_sha256(
            {
                "manifest_sha256": context.manifest_sha256,
                "pipeline_version": self.pipeline_version,
                "calibration_version": context.calibration_version,
                "parameters_sha256": parameters_sha256,
            }
        )
        contact_threshold = int(parameter_snapshot.get("contact_threshold", 0))

        total_load: list[float] = []
        left_load: list[float] = []
        right_load: list[float] = []
        anterior_load: list[float] = []
        posterior_load: list[float] = []
        contact_area: list[int] = []
        cop_xy: list[tuple[float | None, float | None]] = []
        sensor_load_sums = [0.0] * SENSOR_POINTS

        for frame in raw_session.frames:
            if len(frame) != SENSOR_POINTS:
                raise ValueError("each frame must match the approved 48x64 sensor shape")
            if any(value < 0 or value > 0x0FFF for value in frame):
                raise ValueError("frame values must be 12-bit unsigned sensor counts")

            total = float(sum(frame))
            left = float(
                sum(
                    frame[row * SENSOR_COLUMNS + column]
                    for row in range(SENSOR_ROWS)
                    for column in range(SENSOR_COLUMNS // 2)
                )
            )
            anterior = float(sum(frame[: SENSOR_POINTS // 2]))
            weighted_x = 0.0
            weighted_y = 0.0
            contacts = 0
            for index, value in enumerate(frame):
                sensor_load_sums[index] += value
                if value > contact_threshold:
                    contacts += 1
                row, column = divmod(index, SENSOR_COLUMNS)
                weighted_x += value * column
                weighted_y += value * row

            total_load.append(total)
            left_load.append(left)
            right_load.append(total - left)
            anterior_load.append(anterior)
            posterior_load.append(total - anterior)
            contact_area.append(contacts)
            if total == 0:
                cop_xy.append((None, None))
            else:
                cop_xy.append((weighted_x / total, weighted_y / total))

        return FeatureSet(
            tenant_id=context.tenant_id,
            session_id=context.session_id,
            manifest_sha256=context.manifest_sha256,
            calibration_version=context.calibration_version,
            pipeline_version=self.pipeline_version,
            parameters_sha256=parameters_sha256,
            cache_key=cache_key,
            total_load_by_frame=tuple(total_load),
            left_load_by_frame=tuple(left_load),
            right_load_by_frame=tuple(right_load),
            anterior_load_by_frame=tuple(anterior_load),
            posterior_load_by_frame=tuple(posterior_load),
            contact_area_by_frame=tuple(contact_area),
            cop_xy_by_frame=tuple(cop_xy),
            actual_sample_rate_hz=context.actual_sample_rate_hz,
            mean_sensor_load=(
                tuple(value / len(raw_session.frames) for value in sensor_load_sums)
                if raw_session.frames
                else ()
            ),
        )


@dataclass(frozen=True, slots=True)
class StageFeatureSet:
    stage_id: StageId
    completion_time_s: float
    cop_path_mm: float
    mean_velocity_mm_s: float
    ap_mean_velocity_mm_s: float
    ml_mean_velocity_mm_s: float
    ap_rms_mm: float
    ml_rms_mm: float
    ap_range_90_mm: float
    ml_range_90_mm: float
    ellipse_area_95_mm2: float
    total_force_cv: float
    contact_area_variation_mm2: float | None
    timestamps_s: tuple[float, ...]
    cop_ml_mm: tuple[float, ...]
    cop_ap_mm: tuple[float, ...]
    valid_frame_count: int
    total_frame_count: int
    gap_count: int


@dataclass(frozen=True, slots=True)
class SessionFeatureSet:
    session_id: str
    pipeline_version: str
    parameters_sha256: str
    stages: tuple[StageFeatureSet, ...]

    def stage(self, stage_id: StageId) -> StageFeatureSet:
        for stage in self.stages:
            if stage.stage_id is stage_id:
                return stage
        raise KeyError(stage_id)

    def eyes_closed_ratio(self, metric_name: str) -> float:
        eyes_open = self.stage(StageId.BILATERAL_EYES_OPEN)
        eyes_closed = self.stage(StageId.BILATERAL_EYES_CLOSED)
        denominator = max(abs(float(getattr(eyes_open, metric_name))), 1e-9)
        return float(getattr(eyes_closed, metric_name)) / denominator

    def semi_tandem_ratio(self, stage_id: StageId, metric_name: str) -> float:
        baseline = self.stage(StageId.BILATERAL_EYES_OPEN)
        stage = self.stage(stage_id)
        denominator = max(abs(float(getattr(baseline, metric_name))), 1e-9)
        return float(getattr(stage, metric_name)) / denominator

    def side_difference(self, metric_name: str) -> float:
        left = self.stage(StageId.SEMI_TANDEM_LEFT_FORWARD)
        right = self.stage(StageId.SEMI_TANDEM_RIGHT_FORWARD)
        numerator = abs(float(getattr(left, metric_name)) - float(getattr(right, metric_name)))
        denominator = max(
            (abs(float(getattr(left, metric_name))) + abs(float(getattr(right, metric_name))))
            / 2.0,
            1e-9,
        )
        return numerator / denominator


def _split_gap_indices(timestamps: np.ndarray, maximum_gap: float) -> tuple[tuple[int, int], ...]:
    if len(timestamps) < 2:
        return ((0, len(timestamps)),) if len(timestamps) else ()
    deltas = np.diff(timestamps)
    nominal = float(np.median(deltas))
    if nominal <= 0:
        return ((0, len(timestamps)),)
    breaks = np.flatnonzero(deltas > nominal * maximum_gap) + 1
    bounds = (0, *[int(index) for index in breaks], len(timestamps))
    return tuple((bounds[index], bounds[index + 1]) for index in range(len(bounds) - 1))


def _filter_track(
    timestamps: np.ndarray,
    ml: np.ndarray,
    ap: np.ndarray,
    parameters: FeatureParameters,
) -> tuple[np.ndarray, np.ndarray]:
    """Apply optional versioned filtering only within contiguous time segments."""

    if len(timestamps) < 3:
        return ml, ap
    segments = _split_gap_indices(timestamps, parameters.maximum_gap_nominal_intervals)
    filtered_ml = ml.copy()
    filtered_ap = ap.copy()
    for start, end in segments:
        if end - start < 3:
            continue
        segment_ml = filtered_ml[start:end]
        segment_ap = filtered_ap[start:end]
        if parameters.despike_window_samples > 1:
            from scipy.signal import medfilt

            kernel = min(parameters.despike_window_samples, end - start)
            if kernel % 2 == 0:
                kernel -= 1
            if kernel >= 3:
                segment_ml = medfilt(segment_ml, kernel_size=kernel)
                segment_ap = medfilt(segment_ap, kernel_size=kernel)
        deltas = np.diff(timestamps[start:end])
        nominal = float(np.median(deltas))
        nyquist = 0.5 / nominal if nominal > 0 else 0.0
        if parameters.lowpass_cutoff_hz > 0 and nyquist > parameters.lowpass_cutoff_hz:
            from scipy.signal import butter, filtfilt

            normal_cutoff = parameters.lowpass_cutoff_hz / nyquist
            b, a = butter(parameters.lowpass_order, normal_cutoff, btype="low")
            pad_length = min(len(segment_ml) - 1, 3 * max(len(a), len(b)))
            if pad_length >= 1 and len(segment_ml) > pad_length:
                segment_ml = filtfilt(b, a, segment_ml, padlen=pad_length)
                segment_ap = filtfilt(b, a, segment_ap, padlen=pad_length)
        filtered_ml[start:end] = segment_ml
        filtered_ap[start:end] = segment_ap
    return filtered_ml, filtered_ap


def _stage_frame_indices(
    session: PhysicalPressureSession,
    protocol_context: StaticBalanceProtocolContext,
    stage_index: int,
) -> tuple[int, ...]:
    stage = protocol_context.stages[stage_index]
    last_stage = stage_index == len(protocol_context.stages) - 1
    return tuple(
        index
        for index, frame in enumerate(session.frames)
        if stage.start_s <= frame.timestamp_s < stage.end_s
        or (last_stage and frame.timestamp_s == stage.end_s)
    )


def _extract_stage_features(
    session: PhysicalPressureSession,
    protocol_context: StaticBalanceProtocolContext,
    stage_index: int,
    parameters: FeatureParameters,
) -> StageFeatureSet:
    stage = protocol_context.stages[stage_index]
    indices = _stage_frame_indices(session, protocol_context, stage_index)
    subject_coordinates = tuple(
        board_to_subject_coordinates(
            x_mm=point.board_x_mm,
            y_mm=point.board_y_mm,
            orientation=stage.subject_orientation,
        )
        for point in session.points
    )
    ml_coordinates = np.asarray([coordinate[0] for coordinate in subject_coordinates])
    ap_coordinates = np.asarray([coordinate[1] for coordinate in subject_coordinates])
    timestamps: list[float] = []
    cop_ml: list[float] = []
    cop_ap: list[float] = []
    total_forces: list[float] = []
    total_frame_count = len(indices)
    for frame_index in indices:
        frame = session.frames[frame_index]
        forces = np.asarray(frame.normal_force_n, dtype=float)
        total_force = float(forces.sum())
        if total_force < parameters.minimum_total_force_n:
            continue
        timestamps.append(frame.timestamp_s)
        cop_ml.append(float(np.dot(forces, ml_coordinates) / total_force))
        cop_ap.append(float(np.dot(forces, ap_coordinates) / total_force))
        total_forces.append(total_force)

    if not timestamps:
        raise ValueError(f"stage {stage.stage_id.value} has no valid physical frames")
    timestamp_array = np.asarray(timestamps, dtype=float)
    ml_array, ap_array = _filter_track(
        timestamp_array,
        np.asarray(cop_ml, dtype=float),
        np.asarray(cop_ap, dtype=float),
        parameters,
    )
    segments = _split_gap_indices(timestamp_array, parameters.maximum_gap_nominal_intervals)
    gap_count = max(len(segments) - 1, 0)
    path = 0.0
    ml_path = 0.0
    ap_path = 0.0
    effective_duration = 0.0
    for start, end in segments:
        if end - start < 2:
            continue
        delta_time = np.diff(timestamp_array[start:end])
        delta_ml = np.diff(ml_array[start:end])
        delta_ap = np.diff(ap_array[start:end])
        path += float(np.linalg.norm(np.column_stack((delta_ml, delta_ap)), axis=1).sum())
        ml_path += float(np.abs(delta_ml).sum())
        ap_path += float(np.abs(delta_ap).sum())
        effective_duration += float(delta_time.sum())
    if effective_duration <= 0:
        raise ValueError(f"stage {stage.stage_id.value} has no usable time interval")
    total_force_array = np.asarray(total_forces, dtype=float)
    mean_force = float(total_force_array.mean())
    force_cv = float(total_force_array.std() / mean_force) if mean_force else 0.0
    covariance = np.cov(np.vstack((ml_array, ap_array)), bias=True)
    determinant = float(np.linalg.det(covariance)) if np.ndim(covariance) == 2 else 0.0
    ellipse_area = float(np.pi * 5.991 * sqrt(max(determinant, 0.0)))
    return StageFeatureSet(
        stage_id=stage.stage_id,
        completion_time_s=stage.actual_completion_s,
        cop_path_mm=path,
        mean_velocity_mm_s=path / effective_duration,
        ap_mean_velocity_mm_s=ap_path / effective_duration,
        ml_mean_velocity_mm_s=ml_path / effective_duration,
        ap_rms_mm=float(np.sqrt(np.mean((ap_array - ap_array.mean()) ** 2))),
        ml_rms_mm=float(np.sqrt(np.mean((ml_array - ml_array.mean()) ** 2))),
        ap_range_90_mm=float(np.quantile(ap_array, 0.95) - np.quantile(ap_array, 0.05)),
        ml_range_90_mm=float(np.quantile(ml_array, 0.95) - np.quantile(ml_array, 0.05)),
        ellipse_area_95_mm2=ellipse_area,
        total_force_cv=force_cv,
        # Public hardware input has no sensitive hardware geometry/area model;
        # contact-area metrics are intentionally unavailable in this pipeline.
        contact_area_variation_mm2=None,
        timestamps_s=tuple(float(value) for value in timestamp_array),
        cop_ml_mm=tuple(float(value) for value in ml_array),
        cop_ap_mm=tuple(float(value) for value in ap_array),
        valid_frame_count=len(timestamps),
        total_frame_count=total_frame_count,
        gap_count=gap_count,
    )


def extract_features(
    session: PhysicalPressureSession,
    protocol_context: StaticBalanceProtocolContext,
    parameters: FeatureParameters,
) -> SessionFeatureSet:
    """Compute V1 physical static-balance features from a standard session."""

    validate_static_balance_protocol_context(protocol_context, session=session)
    stages = tuple(
        _extract_stage_features(session, protocol_context, stage_index, parameters)
        for stage_index in range(len(protocol_context.stages))
    )
    return SessionFeatureSet(
        session_id=session.session_id,
        pipeline_version="static-balance-feature-pipeline/1.0",
        parameters_sha256=_canonical_sha256(asdict(parameters)),
        stages=stages,
    )
