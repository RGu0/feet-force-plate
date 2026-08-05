from __future__ import annotations

from types import SimpleNamespace

from client.app.live_hardware_acquisition import QtLiveHardwareAcquisition


def test_live_hardware_bridge_returns_background_capture_to_the_qt_thread(qtbot) -> None:
    completed: list[object] = []
    failed: list[str] = []
    acquisition = QtLiveHardwareAcquisition(
        lambda session_id: {"session_id": session_id, "committed": True},
        require_stage_completion=False,
    )
    acquisition.set_callbacks(
        on_progress=lambda _elapsed: None,
        on_complete=completed.append,
        on_failure=failed.append,
    )

    acquisition.start_stage("session-1", SimpleNamespace(duration_seconds=20))

    qtbot.waitUntil(lambda: bool(completed))
    assert completed == [{"session_id": "session-1", "committed": True}]
    assert failed == []


def test_live_hardware_bridge_reports_capture_failure_without_calling_completion(qtbot) -> None:
    completed: list[object] = []
    failed: list[str] = []

    def _raise(_session_id: str) -> object:
        raise RuntimeError("serial disconnected")

    acquisition = QtLiveHardwareAcquisition(_raise, require_stage_completion=False)
    acquisition.set_callbacks(
        on_progress=lambda _elapsed: None,
        on_complete=completed.append,
        on_failure=failed.append,
    )

    acquisition.start_stage("session-1", SimpleNamespace(duration_seconds=20))

    qtbot.waitUntil(lambda: bool(failed))
    assert completed == []
    assert failed == ["RuntimeError: serial disconnected"]


def test_live_hardware_bridge_waits_for_the_last_ui_stage_before_delivery(qtbot) -> None:
    completed: list[object] = []
    acquisition = QtLiveHardwareAcquisition(
        lambda session_id: {"session_id": session_id, "committed": True},
        stage_count=1,
    )
    acquisition.set_callbacks(
        on_progress=lambda _elapsed: None,
        on_complete=completed.append,
        on_failure=lambda _message: None,
    )

    acquisition.start_stage("session-1", SimpleNamespace(duration_seconds=1))

    qtbot.wait(150)
    assert completed == []
    qtbot.waitUntil(lambda: bool(completed), timeout=2_000)
