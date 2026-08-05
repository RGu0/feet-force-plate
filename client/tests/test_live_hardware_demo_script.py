from __future__ import annotations

from client.app.live_hardware_demo import static_balance_stage_plan
from scripts.run_dop4864_live_hardware_demo import _confirm_stage_completions


def test_stage_confirmation_is_fail_closed_for_empty_or_negative_answers() -> None:
    answers = iter(("y", "", "n", "YES"))

    confirmations = _confirm_stage_completions(
        static_balance_stage_plan(stage_seconds=20.0),
        input_func=lambda _prompt: next(answers),
    )

    assert confirmations == (True, False, False, True)
