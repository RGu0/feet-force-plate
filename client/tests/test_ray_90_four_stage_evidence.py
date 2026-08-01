from __future__ import annotations

from pathlib import Path

from scripts.run_ray90_four_stage_evidence import collect_evidence


def test_real_four_stage_fixture_proves_capability_gated_local_metrics() -> None:
    evidence = collect_evidence(repository_root=Path(__file__).resolve().parents[2])

    assert evidence["status"] == "PASSED"
    assert evidence["fixture"] == {
        "kind": "deidentified_real_device_four_stage_engineering_replay",
        "sha256": "2495b910bbf7e4fcca0cd0db36dde809f0fd6395bb6060eded44db575acd6f90",
        "frame_count": 1_658,
        "raw_matrices_included_in_evidence": False,
    }
    assert evidence["network_fault"] == "all_socket_construction_rejected"
    assert evidence["stage_count"] == 4
    assert evidence["all_stage_heatmaps"] is True
    assert evidence["all_stage_relative_loads"] is True
    assert evidence["all_stage_customer_metrics"] == [
        "left_load_percent",
        "right_load_percent",
        "total_relative_load",
    ]
    assert evidence["cop_release"] == {
        "status": "WITHHELD",
        "reason": "DURATION_TOO_SHORT",
        "required_duration_seconds": 30.0,
    }
    assert evidence["unvalidated_customer_metrics"] == []
    assert evidence["input_mutated"] is False
    assert evidence["deterministic"] is True
    assert len(evidence["result_sha256"]) == 64
