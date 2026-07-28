from __future__ import annotations

import main
import pytest


def test_default_entry_uses_mandatory_institution_application(monkeypatch) -> None:
    monkeypatch.setattr(main, "run_institution_app", lambda: 11)
    monkeypatch.setattr(main, "run_local_replay", lambda _args: 22)

    assert main.main([]) == 11


def test_replay_is_an_explicit_debug_choice(monkeypatch) -> None:
    monkeypatch.setattr(main, "run_institution_app", lambda: 11)
    monkeypatch.setattr(main, "run_local_replay", lambda args: 22 if args == ["--replay-speed", "8"] else 0)

    assert main.main(["--replay", "--replay-speed", "8"]) == 22


def test_replay_verify_forwards_the_required_output_directory(monkeypatch, tmp_path) -> None:
    output_dir = tmp_path / "validation"
    observed: list[list[str]] = []
    monkeypatch.setattr(main, "run_institution_app", lambda: 11)
    monkeypatch.setattr(
        main,
        "run_local_replay",
        lambda args: observed.append(args) or 33,
    )

    assert main.main(["--replay", "--verify", "--output-dir", str(output_dir)]) == 33
    assert observed == [["--verify", "--output-dir", str(output_dir)]]


def test_verify_cannot_be_used_without_the_explicit_replay_mode(tmp_path) -> None:
    with pytest.raises(SystemExit, match="explicit --replay"):
        main.main(["--verify", "--output-dir", str(tmp_path / "validation")])
