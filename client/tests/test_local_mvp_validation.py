from __future__ import annotations

import json
from pathlib import Path

from client.app import local_entry
from client.app import local_mvp_validation


def test_local_mvp_validation_exports_the_complete_offline_evidence_bundle(
    qapp, tmp_path: Path
) -> None:
    output_dir = tmp_path / "local-mvp-validation"

    assert hasattr(local_entry, "run_local_mvp_validation")
    result = local_entry.run_local_mvp_validation(
        output_dir=output_dir, replay_speed=500
    )

    assert result.exit_code == 0
    summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["local_only"] is True
    assert summary["algorithm_status"] == "DEBUG_READY"
    assert summary["fixture"]["frame_count"] == 1_658
    assert summary["fixture"]["raw_matrices_included"] is False
    assert len(summary["stage_ids"]) == 4
    assert summary["report"]["kind"] == "V1_REPLAY_DEBUG"
    assert (output_dir / "report.pdf").stat().st_size > 0
    assert {
        "01-preflight.png",
        "02-stage-1.png",
        "03-stage-2.png",
        "04-stage-3.png",
        "05-stage-4.png",
        "06-report-preview.png",
    } == {path.name for path in output_dir.glob("*.png")}


def test_fixture_failure_writes_an_offline_failure_summary_without_a_report(
    monkeypatch, qapp, tmp_path: Path
) -> None:
    output_dir = tmp_path / "fixture-failure"
    monkeypatch.setattr(
        local_entry.FixtureReplaySource,
        "from_repository",
        lambda *args: (_ for _ in ()).throw(ValueError("回放数据完整性校验失败")),
    )

    result = local_mvp_validation.run_local_mvp_validation(
        output_dir=output_dir, replay_speed=500
    )

    assert result.exit_code == 1
    summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary == {
        "schema_version": "local-mvp-validation/1",
        "status": "FAILED",
        "local_only": True,
        "error": "回放 fixture 不可用，无法开始本机 MVP 验证",
    }
    assert not (output_dir / "report.pdf").exists()
