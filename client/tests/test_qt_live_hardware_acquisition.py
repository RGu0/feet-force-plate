from __future__ import annotations

import time
from types import SimpleNamespace

import numpy as np
import pytest

from client.app.live_hardware_acquisition import QtLiveHardwareAcquisition
from client.device.protocol import RawFrame


def _frame_at(seconds: float, source_index: int) -> RawFrame:
    values = np.ones((48, 64), dtype=np.uint8)
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


def _stage(stage_id: str):
    return SimpleNamespace(stage_id=stage_id, duration_seconds=20)


def test_bridge_opens_each_stage_manually_without_restarting_capture(qtbot) -> None:
    completed: list[object] = []
    failed: list[str] = []
    progress: list[int] = []
    capture_calls: list[str] = []

    def _capture(session_id: str, gate):
        capture_calls.append(session_id)
        source_index = 0
        stage_times = {"one": (10.0, 30.0), "two": (60.0, 80.0)}
        while not gate.snapshot().session_complete:
            snapshot = gate.snapshot()
            if snapshot.stage_id in stage_times and not snapshot.stage_complete:
                start, end = stage_times[snapshot.stage_id]
                gate.observe(_frame_at(start, source_index))
                source_index += 1
                gate.observe(_frame_at(end, source_index))
                source_index += 1
            else:
                time.sleep(0.001)
        return SimpleNamespace(committed=True, stage_windows=gate.snapshot().completed_windows)

    acquisition = QtLiveHardwareAcquisition(
        _capture, expected_stage_ids=("one", "two")
    )
    acquisition.set_callbacks(
        on_progress=progress.append,
        on_complete=completed.append,
        on_failure=failed.append,
    )

    acquisition.start_stage("session-1", _stage("one"))
    qtbot.waitUntil(lambda: progress.count(20) == 1)

    assert capture_calls == ["session-1"]
    assert completed == []
    qtbot.wait(150)
    assert progress.count(20) == 1

    acquisition.start_stage("session-1", _stage("two"))
    qtbot.waitUntil(lambda: bool(completed))

    assert capture_calls == ["session-1"]
    assert progress.count(20) == 2
    assert completed[0].committed
    assert [window.stage_id for window in completed[0].stage_windows] == ["one", "two"]
    assert failed == []


def test_bridge_reports_failure_and_can_retry_same_stage_with_new_worker(qtbot) -> None:
    completed: list[object] = []
    failed: list[str] = []
    capture_calls = 0

    def _capture(_session_id: str, gate):
        nonlocal capture_calls
        capture_calls += 1
        if capture_calls == 1:
            gate.cancel_current_stage()
            raise RuntimeError("serial disconnected")
        gate.observe(_frame_at(10, 0))
        gate.observe(_frame_at(30, 1))
        return SimpleNamespace(committed=True, stage_windows=gate.snapshot().completed_windows)

    acquisition = QtLiveHardwareAcquisition(_capture, expected_stage_ids=("one",))
    acquisition.set_callbacks(
        on_progress=lambda _elapsed: None,
        on_complete=completed.append,
        on_failure=failed.append,
    )

    acquisition.start_stage("session-1", _stage("one"))
    qtbot.waitUntil(lambda: bool(failed))
    acquisition.start_stage("session-1", _stage("one"))
    qtbot.waitUntil(lambda: bool(completed))

    assert failed == ["RuntimeError: serial disconnected"]
    assert capture_calls == 2
    assert completed[0].committed


def test_bridge_rejects_session_change_without_opening_another_window(qtbot) -> None:
    def _capture(_session_id: str, gate):
        while not gate.snapshot().cancelled:
            time.sleep(0.001)
        raise RuntimeError("cancelled")

    acquisition = QtLiveHardwareAcquisition(
        _capture, expected_stage_ids=("one", "two")
    )
    acquisition.set_callbacks(
        on_progress=lambda _elapsed: None,
        on_complete=lambda _result: None,
        on_failure=lambda _message: None,
    )
    acquisition.start_stage("session-1", _stage("one"))

    with pytest.raises(RuntimeError, match="cannot span sessions"):
        acquisition.start_stage("session-2", _stage("two"))

    acquisition.stop("session-1")
