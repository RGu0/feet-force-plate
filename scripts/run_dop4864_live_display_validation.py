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
from client.app.heatmap import PhysicalGridOverlay
from client.app.live_display import LiveDisplayProjection
from client.device.acquisition import LatestFrameMailbox
from client.device.protocol import DaoOneP4864Parser, ProtocolProfile
from client.device.serial_transport import SerialByteTransport
from client.device.transport import TransportDisconnected
from client.hardware_standardization.live_processing import (
    DoP4864LiveFrameStandardizer,
    DoP4864LiveProcessingProfile,
)
from client.hardware_standardization.models import BaselineReference
from client.hardware_standardization.do_p4864 import DoP4864StandardizationAdapter
from client.local_analysis.display import DisplayRefreshController, LatestDisplayFrameMailbox
from client.workflow.models import WorkflowState
from client.workflow.state_machine import ScreeningStep


class _ValidationCoordinator:
    """Minimal UI-state port for a display-only validation run."""

    def __init__(self) -> None:
        self._remaining_seconds = 30
        self._instruction = "请保持自然站立，不要说话或大幅移动"

    @property
    def state(self) -> WorkflowState:
        return WorkflowState(
            step=ScreeningStep.ACQUIRING,
            remaining_seconds=self._remaining_seconds,
            acquisition_instruction=self._instruction,
        )

    def observe_acquisition_elapsed(self, *, elapsed_seconds: int) -> int:
        self._remaining_seconds = max(0, 30 - elapsed_seconds)
        return self._remaining_seconds

    def stop_acquisition(self) -> bool:
        return True

    def export_current_report(self, destination: Path) -> None:
        _ = destination

    def print_current_report(self) -> None: ...


def _profile() -> ProtocolProfile:
    return ProtocolProfile.observed_compact_8bit(
        version="do-p4864/observed-compact-column-major-48x64-20260721"
    )


def _processing_profile(path: Path) -> DoP4864LiveProcessingProfile:
    """Load the approved live baseline and known-bad mask; never invent either."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    baseline = payload["baseline_reference"]
    reference = BaselineReference(
        schema_version=baseline["schema_version"],
        baseline_window_id=baseline["baseline_window_id"],
        layout_digest=baseline["layout_digest"],
        zero_offset_count=tuple(float(value) for value in baseline["zero_offset_count"]),
        noise_mad_count=tuple(float(value) for value in baseline["noise_mad_count"]),
        rules_version=baseline["rules_version"],
        threshold_version=baseline["threshold_version"],
        source_digest=baseline["source_digest"],
    )
    cells = frozenset(
        (int(row), int(column)) for row, column in payload.get("known_excluded_cells", ())
    )
    return DoP4864LiveProcessingProfile(
        version=str(payload["version"]),
        baseline_reference=reference,
        known_excluded_cells=cells,
    )


def validate(
    *,
    device: str,
    seconds: float,
    screenshot: Path | None,
    processing_profile: DoP4864LiveProcessingProfile,
) -> dict[str, Any]:
    if seconds <= 0:
        raise ValueError("seconds must be positive")
    specification = DoP4864StandardizationAdapter.observed_compact_8bit().specification
    raw_mailbox = LatestFrameMailbox()
    display_mailbox = LatestDisplayFrameMailbox()
    bridge = LiveDisplayProjection(
        source=raw_mailbox,
        destination=display_mailbox,
        standardizer=DoP4864LiveFrameStandardizer(processing_profile),
    )
    app = QApplication.instance() or QApplication([])
    coordinator = _ValidationCoordinator()
    controller = ApplicationController(
        coordinator,
        display_refresh=DisplayRefreshController(
            display_mailbox,
            maximum_refresh_hz=specification.observed_frame_rate_hz,
        ),
        live_display=bridge,
        physical_grid=PhysicalGridOverlay.from_device_specification(specification),
    )
    controller.window.resize(1280, 800)
    controller.window.show()

    stop = threading.Event()
    outcome: dict[str, Any] = {"frames_observed": 0, "reader_error": None}
    transport_box: dict[str, Any] = {"transport": None}

    def read_device() -> None:
        parser = DaoOneP4864Parser(_profile())
        try:
            transport = SerialByteTransport.open(
                device,
                timeout_seconds=0.25,
                baud_rate=specification.serial_baud_rate,
                data_bits=specification.serial_data_bits,
                parity=specification.serial_parity,
                stop_bits=specification.serial_stop_bits,
            )
            transport_box["transport"] = transport
            while not stop.is_set():
                chunk = transport.read(16_384)
                for frame in parser.feed(chunk):
                    raw_mailbox.publish(frame)
                    outcome["frames_observed"] += 1
        except (OSError, TransportDisconnected) as exc:
            if not stop.is_set():
                outcome["reader_error"] = f"{type(exc).__name__}: {exc}"
        finally:
            transport = transport_box["transport"]
            if transport is not None:
                transport.close()

    reader = threading.Thread(
        target=read_device, name="dop4864-live-display-validation", daemon=True
    )
    reader.start()
    elapsed_seconds = 0
    elapsed_timer = QTimer()

    def advance_clock() -> None:
        nonlocal elapsed_seconds
        elapsed_seconds += 1
        controller.on_acquisition_elapsed(elapsed_seconds)

    elapsed_timer.timeout.connect(advance_clock)
    elapsed_timer.start(1_000)

    def finish() -> None:
        elapsed_timer.stop()
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
        "live_processing_profile": processing_profile.version,
        "device_specification": specification.specification_id,
        "observed_frame_rate_hz": specification.observed_frame_rate_hz,
        "boundary": "Display-only validation; no subject, durable session, analysis result, or report was created.",
    }


def main() -> int:
    arguments = argparse.ArgumentParser(description=__doc__)
    arguments.add_argument("--device", required=True)
    arguments.add_argument("--seconds", type=float, default=10.0)
    arguments.add_argument("--screenshot", type=Path)
    arguments.add_argument(
        "--processing-profile",
        type=Path,
        required=True,
        help="已批准的基线与已知坏区掩码 JSON；真实显示不允许无标准化直通",
    )
    options = arguments.parse_args()
    print(
        json.dumps(
            validate(
                device=options.device,
                seconds=options.seconds,
                screenshot=options.screenshot,
                processing_profile=_processing_profile(options.processing_profile),
            ),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
