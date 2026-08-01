"""Generate sanitized RAY-85 offline-repeatability evidence from the real fixture."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from statistics import median
import time
from unittest.mock import patch

from client.app.fixture_replay import FixtureReplaySource
from client.local_analysis.v1_debug import analyze_v1_replay


_FIXTURE_SHA256 = "2495b910bbf7e4fcca0cd0db36dde809f0fd6395bb6060eded44db575acd6f90"


def _sha256(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def collect_evidence(*, repository_root: Path, runs: int = 3) -> dict[str, object]:
    if runs < 2:
        raise ValueError("at least two runs are required for repeatability evidence")
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
        raise ValueError("RAY-85 evidence requires the approved four-stage fixture")

    elapsed_seconds: list[float] = []
    result_hashes: list[str] = []
    frame_count = 0
    customer_metric_count = 0
    withheld_metric_count = 0
    with patch(
        "socket.socket",
        side_effect=AssertionError("offline analysis attempted to construct a socket"),
    ):
        for _ in range(runs):
            started = time.perf_counter()
            stages = {
                stage_id: tuple(source.frames_for(stage_id))
                for stage_id in source.stage_ids
            }
            result = analyze_v1_replay(stages)
            elapsed_seconds.append(time.perf_counter() - started)
            result_hashes.append(_sha256(asdict(result)))
            frame_count = result.source_frame_count
            customer_metric_count = len(result.customer_metrics)
            withheld_metric_count = len(result.withheld_metrics)

    distinct_hashes = set(result_hashes)
    return {
        "schema_version": "ray-85-offline-analysis-evidence/1",
        "status": "PASSED" if len(distinct_hashes) == 1 else "FAILED",
        "fixture": {
            "kind": "deidentified_real_device_four_stage_engineering_replay",
            "sha256": source.fixture_sha256,
            "frame_count": frame_count,
            "raw_matrices_included_in_evidence": False,
        },
        "boundary": (
            "Engineering replay and local determinism evidence only; not calibrated "
            "physical, customer-report, clinical, or live-hardware evidence."
        ),
        "network_fault": "all_socket_construction_rejected",
        "run_count": runs,
        "distinct_result_sha256_count": len(distinct_hashes),
        "result_sha256": result_hashes[0],
        "elapsed_seconds": elapsed_seconds,
        "median_elapsed_seconds": median(elapsed_seconds),
        "maximum_elapsed_seconds": max(elapsed_seconds),
        "customer_metric_count": customer_metric_count,
        "withheld_metric_count": withheld_metric_count,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args()
    repository_root = Path(__file__).resolve().parents[1]
    evidence = collect_evidence(repository_root=repository_root, runs=args.runs)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0 if evidence["status"] == "PASSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
