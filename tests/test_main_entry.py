from __future__ import annotations

import main


def test_default_entry_uses_mandatory_institution_application(monkeypatch) -> None:
    monkeypatch.setattr(main, "run_institution_app", lambda: 11)
    monkeypatch.setattr(main, "run_local_replay", lambda _args: 22)

    assert main.main([]) == 11


def test_replay_is_an_explicit_debug_choice(monkeypatch) -> None:
    monkeypatch.setattr(main, "run_institution_app", lambda: 11)
    monkeypatch.setattr(main, "run_local_replay", lambda args: 22 if args == ["--replay-speed", "8"] else 0)

    assert main.main(["--replay", "--replay-speed", "8"]) == 22
