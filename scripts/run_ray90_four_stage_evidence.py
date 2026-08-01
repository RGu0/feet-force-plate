"""Generate sanitized RAY-90 evidence from the deidentified four-stage capture."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import numpy as np

from client.app.fixture_replay import FixtureReplaySource
from client.local_analysis.analyzer import analyze_local
from client.local_analysis.models import (
    AnalysisContext,
    CalibrationState,
    LocalQualityStatus,
)
from client.local_analysis.registry import (
    MetricValidationStatus,
    default_metric_registry,
)


_FIXTURE_SHA256 = "2495b910bbf7e4fcca0cd0db36dde809f0fd6395bb6060eded44db575acd6f90"
_SAMPLE_RATE_HZ = 20.0
_PROTOCOL_ID = "standard-static-bilateral"


def _sha256(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _analyze(source: FixtureReplaySource) -> tuple[list[dict[str, object]], str, bool]:
    summaries: list[dict[str, object]] = []
    hash_inputs: list[dict[str, object]] = []
    input_mutated = False
    for stage_id in source.stage_ids:
        frames = tuple(source.frames_for(stage_id))
        matrices = np.asarray([frame.values for frame in frames])
        before = matrices.copy()
        result = analyze_local(
            matrices,
            AnalysisContext(
                sample_rate_hz=_SAMPLE_RATE_HZ,
                duration_seconds=len(frames) / _SAMPLE_RATE_HZ,
                protocol_id=_PROTOCOL_ID,
                protocol_version="four-stage-engineering-replay/1",
                calibration_state=CalibrationState.RELATIVE_ONLY,
                quality_status=LocalQualityStatus.VALID,
            ),
        )
        input_mutated = input_mutated or not np.array_equal(matrices, before)
        customer_keys = sorted(result.customer_metric_map)
        summaries.append(
            {
                "stage_id": stage_id,
                "frame_count": len(frames),
                "duration_seconds": len(frames) / _SAMPLE_RATE_HZ,
                "raw_heatmap_shape": [
                    len(result.raw_count_heatmap or ()),
                    len((result.raw_count_heatmap or ((),))[0]),
                ],
                "relative_heatmap_shape": [
                    len(result.relative_heatmap or ()),
                    len((result.relative_heatmap or ((),))[0]),
                ],
                "customer_metric_keys": customer_keys,
                "left_right_sum_percent": (
                    result.customer_metric_map["left_load_percent"].value
                    + result.customer_metric_map["right_load_percent"].value
                ),
                "cop_release_reason": result.withheld_reason_map["cop_path_length"],
            }
        )
        hash_inputs.append(asdict(result))
    return summaries, _sha256(hash_inputs), input_mutated


def collect_evidence(*, repository_root: Path) -> dict[str, object]:
    fixture_directory = (
        repository_root
        / "tests"
        / "fixtures"
        / "device"
        / "dop4864_reference_protocol_v1"
    )
    source = FixtureReplaySource(
        fixture_directory / "reference-poses.npz",
        fixture_directory / "metadata.json",
    )
    if source.fixture_sha256 != _FIXTURE_SHA256:
        raise ValueError("RAY-90 evidence requires the approved four-stage fixture")

    with patch(
        "socket.socket",
        side_effect=AssertionError("RAY-90 local analysis attempted network access"),
    ):
        first, first_hash, first_mutated = _analyze(source)
        second, second_hash, second_mutated = _analyze(source)

    registry = default_metric_registry()
    cop = registry.get("cop_path_length")
    unvalidated = tuple(
        definition
        for definition in registry.definitions
        if definition.validation_status is MetricValidationStatus.UNVALIDATED
    )
    customer_metric_sets = {tuple(stage["customer_metric_keys"]) for stage in first}
    all_heatmaps = all(
        stage["raw_heatmap_shape"] == [48, 64]
        and stage["relative_heatmap_shape"] == [48, 64]
        for stage in first
    )
    all_loads = all(
        abs(float(stage["left_right_sum_percent"]) - 100.0) <= 1e-9
        for stage in first
    )
    expected_customer_metrics = (
        "left_load_percent",
        "right_load_percent",
        "total_relative_load",
    )
    passed = all(
        (
            len(first) == 4,
            all_heatmaps,
            all_loads,
            customer_metric_sets == {expected_customer_metrics},
            all(stage["cop_release_reason"] == "DURATION_TOO_SHORT" for stage in first),
            not any(definition.customer_visible for definition in unvalidated),
            not first_mutated,
            not second_mutated,
            first == second,
            first_hash == second_hash,
        )
    )
    return {
        "schema_version": "ray-90-four-stage-capability-evidence/1",
        "status": "PASSED" if passed else "FAILED",
        "fixture": {
            "kind": "deidentified_real_device_four_stage_engineering_replay",
            "sha256": source.fixture_sha256,
            "frame_count": sum(int(stage["frame_count"]) for stage in first),
            "raw_matrices_included_in_evidence": False,
        },
        "boundary": (
            "Engineering replay of previously captured relative counts; proves local "
            "software behavior only, not calibration, clinical validity, or live hardware."
        ),
        "network_fault": "all_socket_construction_rejected",
        "stage_count": len(first),
        "all_stage_heatmaps": all_heatmaps,
        "all_stage_relative_loads": all_loads,
        "all_stage_customer_metrics": list(expected_customer_metrics),
        "cop_release": {
            "status": "WITHHELD",
            "reason": "DURATION_TOO_SHORT",
            "required_duration_seconds": cop.required_duration_seconds,
        },
        "unvalidated_customer_metrics": sorted(
            definition.key for definition in unvalidated if definition.customer_visible
        ),
        "metric_definition_fields": [
            "definition",
            "version",
            "unit",
            "required_sample_rate_hz",
            "calibration_requirement",
            "required_duration_seconds",
            "applicable_protocol_ids",
            "validation_status",
            "customer_visible",
        ],
        "input_mutated": first_mutated or second_mutated,
        "deterministic": first == second and first_hash == second_hash,
        "result_sha256": first_hash,
        "stages": first,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    evidence = collect_evidence(repository_root=Path(__file__).resolve().parents[1])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0 if evidence["status"] == "PASSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
