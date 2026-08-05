from __future__ import annotations

from types import SimpleNamespace

from client.app.live_hardware_acquisition import QtLiveHardwareAcquisition


def test_live_hardware_bridge_returns_background_capture_to_the_qt_thread(qtbot) -> None:
    completed: list[object] = []
    failed: list[str] = []
    acquisition = QtLiveHardwareAcquisition(
        lambda session_id: {"session_id": session_id, "committed": True}
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

    acquisition = QtLiveHardwareAcquisition(_raise)
    acquisition.set_callbacks(
        on_progress=lambda _elapsed: None,
        on_complete=completed.append,
        on_failure=failed.append,
    )

    acquisition.start_stage("session-1", SimpleNamespace(duration_seconds=20))

    qtbot.waitUntil(lambda: bool(failed))
    assert completed == []
    assert failed == ["RuntimeError: serial disconnected"]
