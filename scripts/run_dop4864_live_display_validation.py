"""Validate the real-time DO-P4864 → P-07 display path locally.

This is an engineering validation harness, not a screening-session command: it
does not create a subject, durable segment, analysis result, or report.  It
uses the same hardware latest-frame mailbox, application display projection,
and Qt P-07 view as the product composition.  Raw frames stay in memory and
the optional screenshot must be written outside repository evidence.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import threading
from typing import Any

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from client.app.controller import ApplicationController
from client.app.live_display import LiveDisplayProjection
from client.device.acquisition import LatestFrameMailbox
from client.device.protocol import DaoOneP4864Parser, ProtocolProfile
from client.device.serial_transport import SerialByteTransport
from client.device.transport import TransportDisconnected
from client.local_analysis.display import DisplayRefreshController, LatestDisplayFrameMailbox
from client.workflow.models import WorkflowState
from client.workflow.state_machine import ScreeningStep


class _ValidationCoordinator:
    """Minimal UI-state port for a display-only validation run."""

    def __init__(self) -> None:
        self._state = WorkflowState(
            step=ScreeningStep.ACQUIRING,
            remaining_seconds=30,
            acquisition_instruction="请保持自然站立，不要说话或大幅移动",
        )

    @property
    def state(self) -> WorkflowState:
        return self._state

    def observe_acquisition_elapsed(self, *, elapsed_seconds: int) -> int:
        return max(0, 30 - elapsed_seconds)

    def stop_acquisition(self) -> bool:
        return True

    def export_current_report(self, destination: Path) -> None:
        _ = destination

    def print_current_report(self) -> None: ...


def _profile() -> ProtocolProfile:
    return ProtocolProfile.observed_compact_8bit(
        version="do-p4864/observed-compact-column-major-48x64-20260721"
    )


def validate(*, device: str, seconds: float, screenshot: Path | None) -> dict[str, Any]:
    if seconds <= 0:
        raise ValueError("seconds must be positive")
    raw_mailbox = LatestFrameMailbox()
    display_mailbox = LatestDisplayFrameMailbox()
    bridge = LiveDisplayProjection(source=raw_mailbox, destination=display_mailbox)
    app = QApplication.instance() or QApplication([])
    controller = ApplicationController(
        _ValidationCoordinator(),
        display_refresh=DisplayRefreshController(display_mailbox, maximum_refresh_hz=30.0),
        live_display=bridge,
    )
    controller.window.resize(1280, 800)
    controller.window.show()

    stop = threading.Event()
    outcome: dict[str, Any] = {"frames_observed": 0, "reader_error": None}
    transport_box: dict[str, Any] = {"transport": None}

    def read_device() -> None:
        parser = DaoOneP4864Parser(_profile(), allow_unverified=True)
        try:
            transport = SerialByteTransport.open(device, timeout_seconds=0.25)
            transport_box["transport"] = transport
            while not stop.is_set():
                chunk = transport.read(16_384)
                for frame in parser.feed(chunk):
                    raw_mailbox.publish(frame)
                    outcome["frames_observed"] += 1
        except (OSError, TransportDisconnected) as exc:
            outcome["reader_error"] = f"{type(exc).__name__}: {exc}"
        finally:
            transport = transport_box["transport"]
            if transport is not None:
                transport.close()

    reader = threading.Thread(
        target=read_device, name="dop4864-live-display-validation", daemon=True
    )
    reader.start()

    def finish() -> None:
        app.processEvents()
        if screenshot is not None:
            screenshot.parent.mkdir(parents=True, exist_ok=True)
            outcome["screenshot_saved"] = controller.window.grab().save(str(screenshot))
        stop.set()
        transport = transport_box["transport"]
        if transport is not None:
            transport.close()
        QTimer.singleShot(100, app.quit)

    QTimer.singleShot(round(seconds * 1_000), finish)
    app.exec()
    reader.join(timeout=2.0)
    return {
        "schema_version": "do-p4864-live-display-validation/1",
        "requested_duration_seconds": seconds,
        "frames_observed": outcome["frames_observed"],
        "last_source_index": bridge.last_source_index,
        "reader_error": outcome["reader_error"],
        "reader_stopped": not reader.is_alive(),
        "screenshot_saved": bool(outcome.get("screenshot_saved", False)),
        "boundary": "Display-only validation; no subject, durable session, analysis result, or report was created.",
    }


def main() -> int:
    arguments = argparse.ArgumentParser(description=__doc__)
    arguments.add_argument("--device", required=True)
    arguments.add_argument("--seconds", type=float, default=10.0)
    arguments.add_argument("--screenshot", type=Path)
    options = arguments.parse_args()
    print(
        json.dumps(
            validate(
                device=options.device,
                seconds=options.seconds,
                screenshot=options.screenshot,
            ),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
