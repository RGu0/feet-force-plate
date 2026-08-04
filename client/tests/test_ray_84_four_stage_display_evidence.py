from __future__ import annotations

from pathlib import Path

from scripts.run_ray84_four_stage_display_evidence import collect_evidence


def test_sanitized_live_summary_and_four_stage_replay_prove_p07_display_contract() -> None:
    evidence = collect_evidence(
        repository_root=Path(__file__).resolve().parents[2],
        live_evidence_path=(
            Path(__file__).parent
            / "fixtures"
            / "ray_84_live_display_validation.json"
        ),
    )

    assert evidence["status"] == "PASSED"
    assert evidence["real_live_run"] == {
        "frames_observed": 201,
        "last_source_index": 200,
        "reader_error": None,
        "reader_stopped": True,
        "p07_qt_frame_rendered": True,
        "p07_countdown_advanced": True,
    }
    assert evidence["fixture"] == {
        "kind": "deidentified_real_device_four_stage_engineering_replay",
        "sha256": "2495b910bbf7e4fcca0cd0db36dde809f0fd6395bb6060eded44db575acd6f90",
        "frame_count": 1_658,
        "raw_matrices_included_in_evidence": False,
    }
    assert evidence["stage_count"] == 4
    assert evidence["all_stage_display_frames"] is True
    assert evidence["all_stage_heatmap_shape"] == [48, 64]
    assert evidence["all_stage_cop_present"] is True
    assert evidence["all_stage_loads_present"] is True
    assert evidence["source_mutated"] is False
    assert evidence["display_geometry"] == {
        "rows": 48,
        "columns": 64,
        "width_mm": 509.3,
        "height_mm": 381.3,
        "maximum_refresh_hz": 20.7,
    }
    assert len(evidence["result_sha256"]) == 64
