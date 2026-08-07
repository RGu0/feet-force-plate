"""Offline local projection of the canonical physical feature pipeline.

This module consumes only the public ``estimated-force-session/1.0`` contract.
It intentionally exposes the canonical physical features as internal supporting
metrics: customer release remains the cloud capability gate's responsibility.
"""

from __future__ import annotations

from dataclasses import fields
from pathlib import Path

import numpy as np

from client.hardware_standardization.public_export import PhysicalPressureSession
from client.spool.session_commit import read_committed_physical_session
from client.spool.state_store import KeyProvider, StateStore
from cloud.analysis.coordinates import board_to_subject_coordinates
from cloud.analysis.feature_parameters import FeatureParameters
from cloud.analysis.features import StageFeatureSet, extract_features
from cloud.analysis.physical_input import parse_physical_pressure_session
from cloud.analysis.protocol_context import StaticBalanceProtocolContext

from .models import (
    LocalAnalysisResult,
    LocalMetricValue,
    LocalQualityStatus,
    LocalStageProjection,
    WithheldMetric,
)


_RESULT_VERSION = 2
_ALGORITHM_VERSION = "local-physical-analysis/2.0"
_PROTOCOL_ID = "standard-static-balance"
_WITHHELD_REASON = "LOCAL_PHYSICAL_FEATURE_NOT_CUSTOMER_RELEASED"
_RELATIVE_BASIC_VERSION = "physical-relative-basic/2.0"
_MINIMUM_RELATIVE_SAMPLE_RATE_HZ = 10.0
_MINIMUM_RELATIVE_DURATION_S = 10.0
_MAXIMUM_RELATIVE_GAP_INTERVALS = 2.5
_NON_SCALAR_STAGE_FIELDS = frozenset(
    {
        "stage_id",
        "contact_area_variation_mm2",
        "timestamps_s",
        "cop_ml_mm",
        "cop_ap_mm",
    }
)
_SCALAR_STAGE_FIELDS = tuple(
    field.name
    for field in fields(StageFeatureSet)
    if field.name not in _NON_SCALAR_STAGE_FIELDS
)
_UNITS = {
    "completion_time_s": "s",
    "cop_path_mm": "mm",
    "mean_velocity_mm_s": "mm/s",
    "ap_mean_velocity_mm_s": "mm/s",
    "ml_mean_velocity_mm_s": "mm/s",
    "ap_rms_mm": "mm",
    "ml_rms_mm": "mm",
    "ap_range_90_mm": "mm",
    "ml_range_90_mm": "mm",
    "ellipse_area_95_mm2": "mm2",
    "total_force_cv": "ratio",
    "valid_frame_count": "count",
    "total_frame_count": "count",
    "gap_count": "count",
}
_RELEASED_STAGE_FIELDS = {
    "cop_path_mm",
    "mean_velocity_mm_s",
    "ap_mean_velocity_mm_s",
    "ml_mean_velocity_mm_s",
    "ap_range_90_mm",
    "ml_range_90_mm",
    "ellipse_area_95_mm2",
}
_REPORT_STAGE_FEATURES = (
    ("cop_path_mm", "cop_path_mm"),
    ("cop_mean_velocity_mm_s", "mean_velocity_mm_s"),
    ("cop_ml_range_90_mm", "ml_range_90_mm"),
    ("cop_ap_range_90_mm", "ap_range_90_mm"),
    ("cop_ml_mean_velocity_mm_s", "ml_mean_velocity_mm_s"),
    ("cop_ap_mean_velocity_mm_s", "ap_mean_velocity_mm_s"),
    ("cop_ellipse_area_95_mm2", "ellipse_area_95_mm2"),
)


def analyze_committed_physical_session(
    root: str | Path,
    *,
    session_id: str,
    store: StateStore,
    key_provider: KeyProvider,
    protocol_context: StaticBalanceProtocolContext,
    parameters: FeatureParameters,
) -> LocalAnalysisResult:
    """Read one CLOSED/VALID encrypted session and analyze it entirely locally."""

    session = read_committed_physical_session(
        root,
        session_id=session_id,
        store=store,
        key_provider=key_provider,
    )
    return analyze_physical_session(session, protocol_context, parameters)


def analyze_physical_session(
    session: PhysicalPressureSession,
    protocol_context: StaticBalanceProtocolContext,
    parameters: FeatureParameters,
) -> LocalAnalysisResult:
    """Generate a versioned local supporting result without any network call."""

    if session.session_id != protocol_context.session_id:
        raise ValueError("physical session and protocol context session identity mismatch")
    physical_input = parse_physical_pressure_session(session.to_dict())
    feature_set = extract_features(physical_input, protocol_context, parameters)
    definition_version = "|".join(
        (
            feature_set.pipeline_version,
            parameters.version,
            feature_set.parameters_sha256,
        )
    )
    metrics = tuple(
        LocalMetricValue(
            key=f"{stage.stage_id.value}:{field_name}",
            value=float(getattr(stage, field_name)),
            unit=_UNITS[field_name],
            definition_version=definition_version,
        )
        for stage in feature_set.stages
        for field_name in _SCALAR_STAGE_FIELDS
    )
    algorithm_version = "|".join(
        (
            _ALGORITHM_VERSION,
            feature_set.pipeline_version,
            parameters.version,
            feature_set.parameters_sha256,
        )
    )
    relative_definition_version = "|".join(
        (
            _RELATIVE_BASIC_VERSION,
            feature_set.pipeline_version,
            parameters.version,
            feature_set.parameters_sha256,
        )
    )
    release_failure = _relative_release_failure(session, protocol_context)
    if release_failure is None:
        stage_projections = _relative_stage_projections(
            session,
            protocol_context,
            feature_set,
            definition_version=definition_version,
            relative_definition_version=relative_definition_version,
        )
        first_stage = stage_projections[0]
        relative_heatmap = first_stage.relative_heatmap
        customer_metrics = (
            first_stage.metric_map["left_load_percent"],
            first_stage.metric_map["right_load_percent"],
        )
        release_withheld: tuple[WithheldMetric, ...] = ()
        quality_status = LocalQualityStatus.VALID
    else:
        relative_heatmap = None
        stage_projections = ()
        customer_metrics = ()
        release_withheld = (
            WithheldMetric("left_load_percent", release_failure),
            WithheldMetric("right_load_percent", release_failure),
        )
        quality_status = LocalQualityStatus.DEGRADED
    return LocalAnalysisResult(
        result_version=_RESULT_VERSION,
        algorithm_version=algorithm_version,
        protocol_id=_PROTOCOL_ID,
        protocol_version=protocol_context.protocol_version,
        source_frame_count=len(session.frames),
        quality_status=quality_status,
        raw_count_heatmap=None,
        relative_heatmap=relative_heatmap,
        customer_metrics=customer_metrics,
        internal_metrics=metrics,
        withheld_metrics=tuple(
            WithheldMetric(metric.key, _WITHHELD_REASON)
            for metric in metrics
            if metric.key.rsplit(":", 1)[-1] not in _RELEASED_STAGE_FIELDS
        )
        + release_withheld
        + (WithheldMetric("total_force_newton", "CALIBRATION_NOT_VERIFIED"),),
        stage_projections=stage_projections,
    )


def _relative_release_failure(
    session: PhysicalPressureSession,
    protocol_context: StaticBalanceProtocolContext,
) -> str | None:
    for stage_index, stage in enumerate(protocol_context.stages):
        last_stage = stage_index == len(protocol_context.stages) - 1
        timestamps = np.asarray(
            [
                frame.timestamp_s
                for frame in session.frames
                if stage.start_s <= frame.timestamp_s < stage.end_s
                or (last_stage and frame.timestamp_s == stage.end_s)
            ],
            dtype=np.float64,
        )
        deltas = np.diff(timestamps)
        nominal_interval = float(np.median(deltas)) if deltas.size else 0.0
        sample_rate = 1.0 / nominal_interval if nominal_interval > 0 else 0.0
        if sample_rate < _MINIMUM_RELATIVE_SAMPLE_RATE_HZ:
            return "SAMPLE_RATE_TOO_LOW"
        maximum_gap_intervals = (
            float(np.max(deltas) / nominal_interval)
            if nominal_interval > 0 and deltas.size
            else float("inf")
        )
        if maximum_gap_intervals > _MAXIMUM_RELATIVE_GAP_INTERVALS:
            return "GAP_TOO_LARGE"
        observed_duration = (
            float(timestamps[-1] - timestamps[0]) if timestamps.size > 1 else 0.0
        )
        if observed_duration < _MINIMUM_RELATIVE_DURATION_S:
            return "DURATION_TOO_SHORT"
    return None


def _relative_stage_projections(
    session: PhysicalPressureSession,
    protocol_context: StaticBalanceProtocolContext,
    feature_set,
    *,
    definition_version: str,
    relative_definition_version: str,
) -> tuple[LocalStageProjection, ...]:
    """Build one mean relative distribution and descriptive metric set per stage."""

    x_values = tuple(sorted({point.board_x_mm for point in session.points}))
    y_values = tuple(sorted({point.board_y_mm for point in session.points}))
    x_index = {value: index for index, value in enumerate(x_values)}
    y_index = {value: index for index, value in enumerate(y_values)}
    projections: list[LocalStageProjection] = []
    for stage_index, (stage, features) in enumerate(
        zip(protocol_context.stages, feature_set.stages, strict=True)
    ):
        last_stage = stage_index == len(protocol_context.stages) - 1
        frames = tuple(
            frame
            for frame in session.frames
            if stage.start_s <= frame.timestamp_s < stage.end_s
            or (last_stage and frame.timestamp_s == stage.end_s)
        )
        if not frames:
            raise ValueError(f"stage {stage.stage_id.value} requires physical frames")
        mean_force = np.mean(
            np.asarray(
                [frame.estimated_force_n for frame in frames],
                dtype=np.float64,
            ),
            axis=0,
            dtype=np.float64,
        )
        total_force = float(np.sum(mean_force))
        if total_force <= 0:
            raise ValueError(f"stage {stage.stage_id.value} requires positive contact")

        subject_coordinates = tuple(
            board_to_subject_coordinates(
                x_mm=point.board_x_mm,
                y_mm=point.board_y_mm,
                orientation=stage.subject_orientation,
            )
            for point in session.points
        )
        subject_ml = np.asarray(
            [coordinate[0] for coordinate in subject_coordinates], dtype=np.float64
        )
        subject_ap = np.asarray(
            [coordinate[1] for coordinate in subject_coordinates], dtype=np.float64
        )
        left_percent, right_percent = _opposed_load_percentages(
            mean_force, subject_ml
        )
        posterior_percent, anterior_percent = _opposed_load_percentages(
            mean_force, subject_ap
        )

        grid = np.zeros((len(y_values), len(x_values)), dtype=np.float64)
        occupied: set[tuple[int, int]] = set()
        for point, value in zip(session.points, mean_force, strict=True):
            cell = (y_index[point.board_y_mm], x_index[point.board_x_mm])
            if cell in occupied:
                raise ValueError("physical points must map to unique grid cells")
            occupied.add(cell)
            grid[cell] = value
        peak = float(np.max(grid))
        relative = grid / peak if peak > 0 else np.zeros_like(grid)
        metrics = [
            LocalMetricValue(
                key="left_load_percent",
                value=left_percent,
                unit="percent",
                definition_version=relative_definition_version,
            ),
            LocalMetricValue(
                key="right_load_percent",
                value=right_percent,
                unit="percent",
                definition_version=relative_definition_version,
            ),
            LocalMetricValue(
                key="anterior_load_percent",
                value=anterior_percent,
                unit="percent",
                definition_version=relative_definition_version,
            ),
            LocalMetricValue(
                key="posterior_load_percent",
                value=posterior_percent,
                unit="percent",
                definition_version=relative_definition_version,
            ),
        ]
        metrics.extend(
            LocalMetricValue(
                key=report_key,
                value=float(getattr(features, feature_name)),
                unit=_UNITS[feature_name],
                definition_version=definition_version,
            )
            for report_key, feature_name in _REPORT_STAGE_FEATURES
        )
        projections.append(
            LocalStageProjection(
                stage_id=stage.stage_id.value,
                relative_heatmap=tuple(
                    tuple(float(value) for value in row) for row in relative
                ),
                metrics=tuple(metrics),
            )
        )
    return tuple(projections)


def _opposed_load_percentages(
    mean_force: np.ndarray,
    coordinates: np.ndarray,
) -> tuple[float, float]:
    midline = float((np.min(coordinates) + np.max(coordinates)) / 2.0)
    lower_weights = np.where(coordinates < midline, 1.0, 0.0)
    upper_weights = np.where(coordinates > midline, 1.0, 0.0)
    on_midline = np.isclose(coordinates, midline)
    lower_weights[on_midline] = 0.5
    upper_weights[on_midline] = 0.5
    total_force = float(np.sum(mean_force))
    return (
        float(np.dot(mean_force, lower_weights) / total_force * 100.0),
        float(np.dot(mean_force, upper_weights) / total_force * 100.0),
    )
