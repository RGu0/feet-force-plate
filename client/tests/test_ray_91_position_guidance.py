from __future__ import annotations

from client.workflow.protocol import PositionGuidanceController, PositionStatus, default_standard_protocol


def test_stable_position_counts_down_with_text_and_resets_when_subject_leaves() -> None:
    guidance = PositionGuidanceController(default_standard_protocol())

    first = guidance.observe(now_seconds=10.0, contact_ready=True, in_valid_area=True)
    second = guidance.observe(now_seconds=11.0, contact_ready=True, in_valid_area=True)
    reset = guidance.observe(now_seconds=11.5, contact_ready=False, in_valid_area=False)
    restarted = guidance.observe(now_seconds=20.0, contact_ready=True, in_valid_area=True)

    assert first.status is PositionStatus.STABILIZING
    assert first.countdown_seconds == 3
    assert "3 秒" in first.countdown_text
    assert second.countdown_seconds == 2
    assert reset.status is PositionStatus.WAITING
    assert reset.countdown_seconds is None
    assert not reset.manual_start_allowed
    assert restarted.countdown_seconds == 3


def test_auto_start_fires_after_stable_hold_and_manual_start_requires_contact_and_area() -> None:
    guidance = PositionGuidanceController(default_standard_protocol())

    waiting = guidance.observe(
        now_seconds=0.0,
        contact_ready=True,
        in_valid_area=False,
    )
    stable = guidance.observe(
        now_seconds=1.0,
        contact_ready=True,
        in_valid_area=True,
    )
    ready = guidance.observe(
        now_seconds=4.0,
        contact_ready=True,
        in_valid_area=True,
    )

    assert not waiting.manual_start_allowed
    assert stable.manual_start_allowed
    assert not stable.auto_start
    assert ready.status is PositionStatus.READY
    assert ready.auto_start
    assert "自动开始" in ready.countdown_text
