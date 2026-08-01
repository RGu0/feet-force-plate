"""Verify the real CH340 startup gate without starting a screening session.

The command presents the actual ``MandatoryStartupGate`` offscreen, lets its
production connector collect the mandatory unloaded baseline, and reports only
public state names plus whether a workbench was created.  It writes no raw
frames, serial paths, participant data, or credentials.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QWidget

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from client.app.packaged_entry import APP_VERSION, build_mandatory_startup_gate
from client.device.serial_transport import (
    PortAvailability,
    SerialByteTransport,
    enumerate_ch340_ports,
)
from client.hardware_standardization.do_p4864 import DoP4864StandardizationAdapter
from client.startup_validation.workflow import StartupValidationState
from client.spool.state_store import SensitiveBlobCodec, StateStore
from client.startup_validation.persistence import ValidationAuditTrail


_TERMINAL_STATES = frozenset(
    {
        StartupValidationState.PASSED,
        StartupValidationState.DEVICE_NOT_FOUND,
        StartupValidationState.DEVICE_BUSY,
        StartupValidationState.LOAD_NOT_EMPTY,
        StartupValidationState.STREAM_INTERRUPTED,
        StartupValidationState.SIGNAL_INVALID,
        StartupValidationState.SERVICE_REQUIRED,
        StartupValidationState.INTERNAL_ERROR,
    }
)


def _occupy_connected_device() -> SerialByteTransport:
    specification = DoP4864StandardizationAdapter.observed_compact_8bit().specification
    serial_options = {
        "baud_rate": specification.serial_baud_rate,
        "data_bits": specification.serial_data_bits,
        "parity": specification.serial_parity,
        "stop_bits": specification.serial_stop_bits,
    }
    candidates = tuple(enumerate_ch340_ports(**serial_options))
    for candidate in candidates:
        if candidate.availability is PortAvailability.AVAILABLE:
            return SerialByteTransport.open(
                candidate.device, timeout_seconds=0.25, **serial_options
            )
    raise RuntimeError("no available CH340 device could be occupied for the test")


def verify(
    *,
    terminal_id: str,
    timeout_seconds: float,
    occupy_connected_device: bool = False,
    audit_trail: ValidationAuditTrail | None = None,
) -> dict[str, object]:
    if timeout_seconds <= 0:
        raise ValueError("timeout-seconds must be positive")
    app = QApplication.instance() or QApplication([])
    occupying_transport = _occupy_connected_device() if occupy_connected_device else None
    created: list[QWidget] = []
    gate = build_mandatory_startup_gate(
        terminal_id=terminal_id,
        app_version=APP_VERSION,
        workbench_factory=lambda: created.append(QWidget()) or created[-1],
        quit_application=app.quit,
        audit_trail=audit_trail,
    )
    observed_states: list[str] = []
    started = time.monotonic()
    outcome = {"timed_out": False}

    def inspect() -> None:
        state = gate.window.presentation.state
        if not observed_states or observed_states[-1] != state.value:
            observed_states.append(state.value)
        elapsed = time.monotonic() - started
        if gate.workbench is not None or state in _TERMINAL_STATES:
            app.quit()
            return
        if elapsed >= timeout_seconds:
            outcome["timed_out"] = True
            app.quit()

    poll = QTimer()
    poll.timeout.connect(inspect)
    poll.start(50)
    try:
        gate.start()
        app.exec()
        poll.stop()
        inspect()
        for widget in (gate.window, gate.workbench):
            if widget is not None:
                widget.close()
                widget.deleteLater()
    finally:
        if occupying_transport is not None:
            occupying_transport.close()
    return {
        "schema_version": "startup-gate-hardware-acceptance/1",
        "captured_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "terminal_id": terminal_id,
        "observed_states": observed_states,
        "final_state": gate.window.presentation.state.value,
        "workbench_created": gate.workbench is not None,
        "timed_out": outcome["timed_out"],
        "fault_injection": "PORT_HELD_OPEN" if occupy_connected_device else None,
        "boundary": (
            "Startup-gate-only validation; no participant, screening session, raw frame, "
            "serial path, credential, report, or telemetry upload is recorded."
        ),
    }


def verify_load_recovery(
    *,
    terminal_id: str,
    timeout_seconds: float,
    operator_clear_marker: Path,
    operator_clear_timeout_seconds: float,
) -> dict[str, object]:
    """Require a real load failure, then a human-confirmed retry on one gate."""

    if timeout_seconds <= 0:
        raise ValueError("timeout-seconds must be positive")
    if operator_clear_timeout_seconds <= 0:
        raise ValueError("operator-clear-timeout-seconds must be positive")
    if operator_clear_marker.exists():
        raise ValueError("operator-clear-marker must not exist before the run")
    app = QApplication.instance() or QApplication([])
    created: list[QWidget] = []
    gate = build_mandatory_startup_gate(
        terminal_id=terminal_id,
        app_version=APP_VERSION,
        workbench_factory=lambda: created.append(QWidget()) or created[-1],
        quit_application=app.quit,
    )

    def run_attempt(*, retry: bool) -> dict[str, object]:
        observed_states: list[str] = []
        started = time.monotonic()
        outcome = {"timed_out": False}

        def inspect() -> None:
            state = gate.window.presentation.state
            if not observed_states or observed_states[-1] != state.value:
                observed_states.append(state.value)
            if gate.workbench is not None or state in _TERMINAL_STATES:
                app.quit()
                return
            if time.monotonic() - started >= timeout_seconds:
                outcome["timed_out"] = True
                app.quit()

        poll = QTimer()
        poll.timeout.connect(inspect)
        poll.start(50)
        if retry:
            gate.retry()
        else:
            gate.start()
        app.exec()
        poll.stop()
        inspect()
        return {
            "observed_states": observed_states,
            "final_state": gate.window.presentation.state.value,
            "workbench_created": gate.workbench is not None,
            "timed_out": outcome["timed_out"],
        }

    try:
        first_attempt = run_attempt(retry=False)
        if first_attempt["final_state"] != StartupValidationState.LOAD_NOT_EMPTY.value:
            return _load_recovery_result(first_attempt, None, "FIRST_ATTEMPT_NOT_LOAD")
        print(
            "OPERATOR_CLEARANCE_REQUIRED: remove the non-participant test load, "
            "then confirm to retry the same startup gate.",
            flush=True,
        )
        cleared = {"confirmed": False, "timed_out": False}
        waiting_started = time.monotonic()

        def await_operator_clearance() -> None:
            if operator_clear_marker.exists():
                cleared["confirmed"] = True
                app.quit()
                return
            if time.monotonic() - waiting_started >= operator_clear_timeout_seconds:
                cleared["timed_out"] = True
                app.quit()

        marker_poll = QTimer()
        marker_poll.timeout.connect(await_operator_clearance)
        marker_poll.start(100)
        app.exec()
        marker_poll.stop()
        if not cleared["confirmed"]:
            return _load_recovery_result(
                first_attempt,
                None,
                "OPERATOR_CLEARANCE_TIMEOUT" if cleared["timed_out"] else "OPERATOR_CLEARANCE_MISSING",
            )
        second_attempt = run_attempt(retry=True)
        return _load_recovery_result(first_attempt, second_attempt, None)
    finally:
        for widget in (gate.window, gate.workbench):
            if widget is not None:
                widget.close()
                widget.deleteLater()


def _load_recovery_result(
    first_attempt: dict[str, object],
    second_attempt: dict[str, object] | None,
    interruption: str | None,
) -> dict[str, object]:
    return {
        "schema_version": "startup-gate-load-recovery-acceptance/1",
        "captured_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "first_attempt": first_attempt,
        "second_attempt": second_attempt,
        "interruption": interruption,
        "boundary": (
            "One real MandatoryStartupGate only; operator confirmation gates the retry. "
            "No participant, screening session, raw frame, serial path, credential, report, "
            "or telemetry upload is recorded."
        ),
    }


class _EphemeralAuditKeyProvider:
    """Private acceptance-only codec key; audit rows do not store sensitive blobs."""

    def get_key(self) -> bytes:
        return b"\x00" * 32


def _safe_audit_summary(trail: ValidationAuditTrail) -> dict[str, object]:
    events = trail.pending_events(limit=10)
    payloads = [json.loads(event.payload_json) for event in events]
    encoded = json.dumps(payloads, ensure_ascii=False, sort_keys=True)
    forbidden = ("/dev/", "raw_frame", "matrix", "traceback")
    return {
        "pending_event_count": len(events),
        "recorded_outcomes": [payload["outcome"] for payload in payloads],
        "recorded_reasons": [payload["reason"] for payload in payloads],
        "payload_schema_versions": sorted(
            {str(payload["schema_version"]) for payload in payloads}
        ),
        "forbidden_detail_absent": not any(
            marker in encoded.lower() for marker in forbidden
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--terminal-id", default="hardware-acceptance-terminal")
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument(
        "--occupy-connected-device",
        action="store_true",
        help="hold an available CH340 port open to verify the DEVICE_BUSY recovery path",
    )
    parser.add_argument(
        "--expect-state",
        choices=[state.value for state in _TERMINAL_STATES],
        default=StartupValidationState.PASSED.value,
    )
    parser.add_argument(
        "--verify-load-recovery",
        action="store_true",
        help=(
            "require LOAD_NOT_EMPTY, wait for an operator clearance confirmation, then "
            "retry the same gate and require PASSED"
        ),
    )
    parser.add_argument(
        "--operator-clear-marker",
        type=Path,
        help=(
            "one-time file created only after the operator confirms the test load is "
            "removed; required with --verify-load-recovery"
        ),
    )
    parser.add_argument("--operator-clear-timeout-seconds", type=float, default=120.0)
    parser.add_argument(
        "--audit-root",
        type=Path,
        help=(
            "private temporary root for an allow-listed local validation audit; the "
            "summary emits only audit aggregates"
        ),
    )
    parser.add_argument("--summary-output", type=Path)
    args = parser.parse_args()
    store = None
    try:
        audit_trail = None
        if args.audit_root is not None:
            args.audit_root.mkdir(parents=True, exist_ok=True)
            store = StateStore(
                args.audit_root / "state.sqlite3",
                SensitiveBlobCodec(_EphemeralAuditKeyProvider()),
            )
            audit_trail = ValidationAuditTrail(store)
        if args.verify_load_recovery:
            if args.occupy_connected_device:
                parser.error("--verify-load-recovery cannot occupy the connected device")
            if args.operator_clear_marker is None:
                parser.error("--verify-load-recovery requires --operator-clear-marker")
            result = verify_load_recovery(
                terminal_id=args.terminal_id,
                timeout_seconds=args.timeout_seconds,
                operator_clear_marker=args.operator_clear_marker,
                operator_clear_timeout_seconds=args.operator_clear_timeout_seconds,
            )
        else:
            result = verify(
                terminal_id=args.terminal_id,
                timeout_seconds=args.timeout_seconds,
                occupy_connected_device=args.occupy_connected_device,
                audit_trail=audit_trail,
            )
        if audit_trail is not None:
            result["audit"] = _safe_audit_summary(audit_trail)
    finally:
        if store is not None:
            store.close()
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.summary_output is not None:
        args.summary_output.parent.mkdir(parents=True, exist_ok=True)
        args.summary_output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    if args.verify_load_recovery:
        first_attempt = result["first_attempt"]
        second_attempt = result["second_attempt"]
        passed = (
            result["interruption"] is None
            and isinstance(first_attempt, dict)
            and first_attempt["final_state"] == StartupValidationState.LOAD_NOT_EMPTY.value
            and first_attempt["workbench_created"] is False
            and first_attempt["timed_out"] is False
            and isinstance(second_attempt, dict)
            and second_attempt["final_state"] == StartupValidationState.PASSED.value
            and second_attempt["workbench_created"] is True
            and second_attempt["timed_out"] is False
        )
    else:
        expected_pass = args.expect_state == StartupValidationState.PASSED.value
        passed = (
            result["final_state"] == args.expect_state
            and not result["timed_out"]
            and bool(result["workbench_created"]) is expected_pass
        )
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
