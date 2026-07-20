from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

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
