from __future__ import annotations

import numpy as np
import pytest

from client.device.protocol import RawFrame
from client.device.stage_windows import (
    CapturedStageWindow,
    StageRecordingGate,
    validate_captured_stage_windows,
)
from client.workflow.protocol import default_standard_protocol


def _expected_stage_ids() -> tuple[str, ...]:
    return tuple(stage.stage_id for stage in default_standard_protocol().stages)


def _frame_at(seconds: float, *, source_index: int = 0) -> RawFrame:
    values = np.zeros((48, 64), dtype=np.uint8)
    values.setflags(write=False)
    timestamp_ns = round(seconds * 1_000_000_000)
    return RawFrame(
        values=values,
        host_monotonic_ns=timestamp_ns,
        host_wall_time_ns=timestamp_ns,
        source_index=source_index,
        device_frame_seq=None,
        device_timestamp_ns=None,
        quality_flags=frozenset(),
    )


def test_gate_discards_preparation_frames_and_closes_each_manual_window() -> None:
    gate = StageRecordingGate(expected_stage_ids=("one", "two"))

    assert not gate.observe(_frame_at(1.0)).record
    gate.open_stage("one", duration_seconds=20)
    assert gate.observe(_frame_at(10.0, source_index=1)).record
    end = gate.observe(_frame_at(30.0, source_index=2))

    assert end.record and end.stage_complete and not end.session_complete
    assert end.window == CapturedStageWindow("one", 0.0, 20.0, 2)
    assert not gate.snapshot().stage_complete
    assert gate.snapshot().completed_windows == ()
    assert gate.begin_stage_commit(end.window)
    gate.complete_stage_commit(end.window)
    assert gate.snapshot().stage_complete
    assert not gate.observe(_frame_at(35.0, source_index=3)).record

    gate.open_stage("two", duration_seconds=20)
    assert gate.observe(_frame_at(60.0, source_index=4)).record
    final = gate.observe(_frame_at(80.0, source_index=5))

    assert final.record and final.stage_complete and final.session_complete
    assert not gate.snapshot().session_complete
    assert final.window is not None
    assert gate.begin_stage_commit(final.window)
    gate.complete_stage_commit(final.window)
    assert gate.snapshot().completed_windows == (
        CapturedStageWindow("one", 0.0, 20.0, 2),
        CapturedStageWindow("two", 50.0, 70.0, 2),
    )


def test_boundary_waits_for_durable_ack_and_can_cancel_pending_stage() -> None:
    gate = StageRecordingGate(expected_stage_ids=("one",))
    gate.open_stage("one", duration_seconds=20)
    gate.observe(_frame_at(10.0))

    boundary = gate.observe(_frame_at(30.0, source_index=1))

    assert boundary.stage_complete
    assert boundary.window is not None
    assert gate.snapshot().elapsed_seconds == 20
    assert not gate.snapshot().stage_complete
    assert gate.snapshot().completed_windows == ()
    with pytest.raises(RuntimeError, match="durable acknowledgement"):
        gate.open_stage("one", duration_seconds=20)

    gate.cancel_current_stage()
    gate.open_stage("one", duration_seconds=20)
    assert not gate.snapshot().cancelled


def test_worker_rejects_ui_cancellation_requested_before_stage_commit() -> None:
    gate = StageRecordingGate(expected_stage_ids=("one",))
    gate.open_stage("one", duration_seconds=20)
    gate.observe(_frame_at(10.0))
    boundary = gate.observe(_frame_at(30.0, source_index=1))
    assert boundary.window is not None

    assert gate.request_cancellation()
    assert gate.snapshot().cancelled
    assert not gate.begin_stage_commit(boundary.window)

    assert gate.snapshot().completed_windows == ()
    gate.open_stage("one", duration_seconds=20)
    assert not gate.snapshot().cancelled


def test_ui_cancellation_cannot_split_worker_commit_and_acknowledgement() -> None:
    gate = StageRecordingGate(expected_stage_ids=("one",))
    gate.open_stage("one", duration_seconds=20)
    gate.observe(_frame_at(10.0))
    boundary = gate.observe(_frame_at(30.0, source_index=1))
    assert boundary.window is not None

    assert gate.begin_stage_commit(boundary.window)
    assert not gate.request_cancellation()
    gate.complete_stage_commit(boundary.window)

    snapshot = gate.snapshot()
    assert snapshot.stage_complete
    assert snapshot.session_complete
    assert not snapshot.cancelled
    assert snapshot.completed_windows == (boundary.window,)


def test_gate_rejects_active_out_of_order_or_cross_session_stage_changes() -> None:
    gate = StageRecordingGate(expected_stage_ids=("one", "two"))
    gate.bind_session("session-1")

    with pytest.raises(ValueError, match="stage order"):
        gate.open_stage("two", duration_seconds=20)

    gate.open_stage("one", duration_seconds=20)
    with pytest.raises(RuntimeError, match="already active"):
        gate.open_stage("one", duration_seconds=20)
    with pytest.raises(RuntimeError, match="cannot span sessions"):
        gate.bind_session("session-2")


def test_cancelled_gate_can_retry_only_the_same_unfinished_stage() -> None:
    gate = StageRecordingGate(expected_stage_ids=("one", "two"))
    gate.open_stage("one", duration_seconds=20)
    assert gate.observe(_frame_at(10.0)).record

    gate.cancel_current_stage()

    assert gate.snapshot().cancelled
    gate.open_stage("one", duration_seconds=20)
    assert not gate.snapshot().cancelled
    assert gate.observe(_frame_at(40.0, source_index=1)).record


def test_captured_windows_allow_preparation_gaps_but_require_protocol_order() -> None:
    windows = (
        CapturedStageWindow("BILATERAL_EYES_OPEN", 0.0, 20.0, 600),
        CapturedStageWindow("BILATERAL_EYES_CLOSED", 34.5, 54.5, 601),
        CapturedStageWindow("SEMI_TANDEM_LEFT_FORWARD", 70.0, 90.0, 599),
        CapturedStageWindow("SEMI_TANDEM_RIGHT_FORWARD", 105.0, 125.0, 602),
    )

    assert validate_captured_stage_windows(
        windows,
        expected_stage_ids=_expected_stage_ids(),
        minimum_duration_s=20.0,
    ) == windows


@pytest.mark.parametrize(
    "windows",
    (
        (),
        (
            CapturedStageWindow("BILATERAL_EYES_OPEN", 0.0, 20.0, 600),
            CapturedStageWindow("BILATERAL_EYES_OPEN", 34.5, 54.5, 601),
            CapturedStageWindow("SEMI_TANDEM_LEFT_FORWARD", 70.0, 90.0, 599),
            CapturedStageWindow("SEMI_TANDEM_RIGHT_FORWARD", 105.0, 125.0, 602),
        ),
        (
            CapturedStageWindow("BILATERAL_EYES_CLOSED", 0.0, 20.0, 600),
            CapturedStageWindow("BILATERAL_EYES_OPEN", 34.5, 54.5, 601),
            CapturedStageWindow("SEMI_TANDEM_LEFT_FORWARD", 70.0, 90.0, 599),
            CapturedStageWindow("SEMI_TANDEM_RIGHT_FORWARD", 105.0, 125.0, 602),
        ),
        (
            CapturedStageWindow("BILATERAL_EYES_OPEN", 0.0, 20.0, 600),
            CapturedStageWindow("BILATERAL_EYES_CLOSED", 19.5, 39.5, 601),
            CapturedStageWindow("SEMI_TANDEM_LEFT_FORWARD", 70.0, 90.0, 599),
            CapturedStageWindow("SEMI_TANDEM_RIGHT_FORWARD", 105.0, 125.0, 602),
        ),
        (
            CapturedStageWindow("BILATERAL_EYES_OPEN", 0.0, 20.0, 600),
            CapturedStageWindow("BILATERAL_EYES_CLOSED", 34.5, 54.49, 601),
            CapturedStageWindow("SEMI_TANDEM_LEFT_FORWARD", 70.0, 90.0, 599),
            CapturedStageWindow("SEMI_TANDEM_RIGHT_FORWARD", 105.0, 125.0, 602),
        ),
    ),
)
def test_captured_windows_reject_missing_duplicate_reordered_overlapping_or_short_stages(
    windows: tuple[CapturedStageWindow, ...],
) -> None:
    with pytest.raises(ValueError, match="captured stage windows"):
        validate_captured_stage_windows(
            windows,
            expected_stage_ids=_expected_stage_ids(),
            minimum_duration_s=20.0,
        )


@pytest.mark.parametrize(
    "stage_id,start_s,end_s,frame_count",
    (
        ("", 0.0, 20.0, 1),
        ("BILATERAL_EYES_OPEN", -0.1, 20.0, 1),
        ("BILATERAL_EYES_OPEN", 20.0, 20.0, 1),
        ("BILATERAL_EYES_OPEN", 0.0, 20.0, 0),
    ),
)
def test_captured_stage_window_rejects_invalid_timing_or_frames(
    stage_id: str, start_s: float, end_s: float, frame_count: int
) -> None:
    with pytest.raises(ValueError):
        CapturedStageWindow(stage_id, start_s, end_s, frame_count)
