"""Generate sanitized RAY-84 P-07 evidence without opening the hardware device."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import numpy as np

from client.app.fixture_replay import FixtureReplaySource
from client.app.live_display import LiveDisplayProjection
from client.hardware_standardization.live_processing import replay_debug_profile
from client.hardware_standardization.runtime import active_hardware_runtime
from client.local_analysis.display import LatestDisplayFrameMailbox


_FIXTURE_SHA256 = "2495b910bbf7e4fcca0cd0db36dde809f0fd6395bb6060eded44db575acd6f90"


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_json(value: object) -> str:
    return _sha256_bytes(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    )


def _stage_display_summary(
    source: FixtureReplaySource,
    stage_id: str,
) -> tuple[dict[str, object], bool]:
    hardware = active_hardware_runtime()
    raw_mailbox = hardware.make_latest_frame_mailbox()
    display_mailbox = LatestDisplayFrameMailbox()
    bridge = LiveDisplayProjection(
        source=raw_mailbox,
        destination=display_mailbox,
        standardizer=hardware.make_live_standardizer(
            replay_debug_profile(fixture_sha256=source.fixture_sha256)
        ),
    )
    source_mutated = False
    observed = 0
    latest = None
    for frame in source.frames_for(stage_id):
        before = frame.values.copy()
        raw_mailbox.publish(frame)
        latest = bridge.poll()
        source_mutated = source_mutated or not np.array_equal(frame.values, before)
        observed += 1
    if latest is None:
        raise ValueError(f"stage {stage_id} did not emit a display frame")
    rows = len(latest.relative_heatmap)
    columns = len(latest.relative_heatmap[0])
    return (
        {
            "stage_id": stage_id,
            "source_frame_count": observed,
            "last_source_index": bridge.last_source_index,
            "display_heatmap_shape": [rows, columns],
            "cop_present": latest.cop_x is not None and latest.cop_y is not None,
            "total_relative_load_positive": latest.total_relative_load > 0,
            "left_right_sum_percent": (
                latest.left_load_percent + latest.right_load_percent
            ),
            "capture_timestamp_preserved": abs(
                latest.captured_monotonic_seconds - bridge.last_source_index * 0.05
            )
            <= 1e-12,
        },
        source_mutated,
    )


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
        raise ValueError("RAY-84 evidence requires the approved four-stage fixture")

    live_path = (
        repository_root
        / "docs"
        / "evidence"
        / "linear"
        / "RAY-84"
        / "live-display-validation-success-20260723.json"
    )
    live = json.loads(live_path.read_text(encoding="utf-8"))
    checks = live["checks"]
    real_live_run = {
        "frames_observed": live["frames_observed"],
        "last_source_index": live["last_source_index"],
        "reader_error": live["reader_error"],
        "reader_stopped": live["reader_stopped"],
        "p07_qt_frame_rendered": checks["p07_qt_frame_rendered"],
        "p07_countdown_advanced": checks["p07_countdown_advanced"],
    }

    stages: list[dict[str, object]] = []
    source_mutated = False
    with patch(
        "socket.socket",
        side_effect=AssertionError("RAY-84 local display replay attempted network access"),
    ):
        for stage_id in source.stage_ids:
            summary, mutated = _stage_display_summary(source, stage_id)
            stages.append(summary)
            source_mutated = source_mutated or mutated

    geometry = active_hardware_runtime().display_geometry
    geometry_summary = {
        "rows": geometry.rows,
        "columns": geometry.columns,
        "width_mm": geometry.width_mm,
        "height_mm": geometry.height_mm,
        "maximum_refresh_hz": geometry.maximum_refresh_hz,
    }
    expected_shape = [geometry.rows, geometry.columns]
    all_stage_frames = all(
        int(stage["source_frame_count"]) >= 400
        and int(stage["last_source_index"]) == int(stage["source_frame_count"]) - 1
        and stage["capture_timestamp_preserved"] is True
        for stage in stages
    )
    all_cop = all(stage["cop_present"] is True for stage in stages)
    all_loads = all(
        stage["total_relative_load_positive"] is True
        and abs(float(stage["left_right_sum_percent"]) - 100.0) <= 1e-9
        for stage in stages
    )
    all_shapes = all(stage["display_heatmap_shape"] == expected_shape for stage in stages)
    live_passed = real_live_run == {
        "frames_observed": 201,
        "last_source_index": 200,
        "reader_error": None,
        "reader_stopped": True,
        "p07_qt_frame_rendered": True,
        "p07_countdown_advanced": True,
    }
    hash_input = {
        "real_live_run": real_live_run,
        "live_evidence_sha256": _sha256_bytes(live_path.read_bytes()),
        "fixture_sha256": source.fixture_sha256,
        "display_geometry": geometry_summary,
        "stages": stages,
    }
    passed = all(
        (
            live_passed,
            len(stages) == 4,
            all_stage_frames,
            all_shapes,
            all_cop,
            all_loads,
            not source_mutated,
        )
    )
    return {
        "schema_version": "ray-84-four-stage-display-evidence/1",
        "status": "PASSED" if passed else "FAILED",
        "real_live_run": real_live_run,
        "real_live_evidence_sha256": hash_input["live_evidence_sha256"],
        "fixture": {
            "kind": "deidentified_real_device_four_stage_engineering_replay",
            "sha256": source.fixture_sha256,
            "frame_count": sum(int(stage["source_frame_count"]) for stage in stages),
            "raw_matrices_included_in_evidence": False,
        },
        "boundary": (
            "The saved live run proves the real CH340-to-P-07 path. The four-stage "
            "replay proves current deterministic display behavior; neither is clinical evidence."
        ),
        "stage_count": len(stages),
        "all_stage_display_frames": all_stage_frames,
        "all_stage_heatmap_shape": expected_shape if all_shapes else None,
        "all_stage_cop_present": all_cop,
        "all_stage_loads_present": all_loads,
        "source_mutated": source_mutated,
        "display_geometry": geometry_summary,
        "result_sha256": _sha256_json(hash_input),
        "stages": stages,
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
