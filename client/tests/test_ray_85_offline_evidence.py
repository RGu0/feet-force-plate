from __future__ import annotations

from pathlib import Path

from scripts.run_ray85_offline_analysis_evidence import collect_evidence


def test_real_four_stage_fixture_is_repeatable_with_network_hard_failed() -> None:
    evidence = collect_evidence(repository_root=Path(__file__).resolve().parents[2], runs=2)

    assert evidence["status"] == "PASSED"
    assert evidence["fixture"] == {
        "kind": "deidentified_real_device_four_stage_engineering_replay",
        "sha256": "2495b910bbf7e4fcca0cd0db36dde809f0fd6395bb6060eded44db575acd6f90",
        "frame_count": 1_658,
        "raw_matrices_included_in_evidence": False,
    }
    assert evidence["network_fault"] == "all_socket_construction_rejected"
    assert evidence["run_count"] == 2
    assert evidence["distinct_result_sha256_count"] == 1
    assert len(evidence["elapsed_seconds"]) == 2
    assert all(value > 0 for value in evidence["elapsed_seconds"])
    assert evidence["customer_metric_count"] == 0
    assert evidence["withheld_metric_count"] == 16
