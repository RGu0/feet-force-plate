"""Record a privacy-safe real-device diagnostic for the startup load detector.

The command uses the same production CH340 discovery and parser boundary as
mandatory startup validation.  It never starts a screening session and emits
only detector-hit counts, parser integrity counters, and version identifiers;
raw matrices, device paths, threshold values, positions, participant data, and
credentials are neither printed nor written to the summary.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from client.device.transport import TransportDisconnected
from client.hardware_standardization.do_p4864 import DoP4864StandardizationAdapter
from client.startup_validation.rules import (
    ValidationThresholds,
    observe_load_detector,
)
from client.startup_validation.serial_connector import SerialValidationConnector
from client.startup_validation.workflow import DeviceBusy, DeviceNotFound


def capture(*, duration_seconds: float) -> dict[str, object]:
    """Capture only aggregate detector results from the production input path."""

    specification = DoP4864StandardizationAdapter.observed_compact_8bit().specification
    if duration_seconds < specification.baseline_min_duration_s:
        raise ValueError("duration-seconds must meet the selected device specification")
    try:
        connection = SerialValidationConnector().connect()
    except DeviceNotFound:
        return _unavailable("DEVICE_NOT_FOUND")
    except DeviceBusy:
        return _unavailable("DEVICE_BUSY")

    thresholds = _thresholds()
    valid_frame_count = 0
    detector_hit_frame_count = 0
    mean_guard_hit_frame_count = 0
    active_area_guard_hit_frame_count = 0
    deadline = time.monotonic() + duration_seconds
    terminal_status = "COMPLETED"
    try:
        while time.monotonic() < deadline:
            try:
                chunk = connection.transport.read(16_384)
            except TransportDisconnected:
                terminal_status = "STREAM_INTERRUPTED"
                break
            if not chunk:
                continue
            for frame in connection.parser.feed(chunk):
                valid_frame_count += 1
                observation = observe_load_detector(frame, thresholds)
                detector_hit_frame_count += int(observation.detected)
                mean_guard_hit_frame_count += int(observation.mean_guard_triggered)
                active_area_guard_hit_frame_count += int(
                    observation.active_area_guard_triggered
                )
    finally:
        connection.transport.close()

    if valid_frame_count == 0 and terminal_status == "COMPLETED":
        terminal_status = "NO_VALID_SIGNAL"
    return {
        "schema_version": "startup-load-detector-diagnostic/1",
        "captured_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "terminal_status": terminal_status,
        "detector_result": (
            "DETECTED" if detector_hit_frame_count else "NOT_DETECTED"
        ),
        "valid_frame_count": valid_frame_count,
        "detector_hit_frame_count": detector_hit_frame_count,
        "mean_guard_hit_frame_count": mean_guard_hit_frame_count,
        "active_area_guard_hit_frame_count": active_area_guard_hit_frame_count,
        "versions": {
            "rules": thresholds.rules_version,
            "threshold": thresholds.version,
        },
        "boundary": (
            "Production CH340 discovery and parser only; no startup UI, participant, "
            "screening session, raw frame, device path, threshold value, load position, "
            "or credential is recorded."
        ),
    }


def _unavailable(terminal_status: str) -> dict[str, object]:
    return {
        "schema_version": "startup-load-detector-diagnostic/1",
        "captured_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "terminal_status": terminal_status,
        "detector_result": "NOT_RUN",
        "valid_frame_count": 0,
        "detector_hit_frame_count": 0,
        "mean_guard_hit_frame_count": 0,
        "active_area_guard_hit_frame_count": 0,
        "versions": {
            "rules": _thresholds().rules_version,
            "threshold": _thresholds().version,
        },
        "boundary": (
            "Production CH340 discovery only; no device was opened and no participant, "
            "screening session, raw frame, device path, threshold value, load position, "
            "or credential is recorded."
        ),
    }


def _thresholds() -> ValidationThresholds:
    return ValidationThresholds.from_device_specification(
        DoP4864StandardizationAdapter.observed_compact_8bit().specification
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration-seconds", type=float)
    parser.add_argument(
        "--expect-result",
        choices=("DETECTED", "NOT_DETECTED"),
        default="DETECTED",
    )
    parser.add_argument("--summary-output", type=Path)
    args = parser.parse_args()
    specification = DoP4864StandardizationAdapter.observed_compact_8bit().specification
    result = capture(
        duration_seconds=(
            specification.baseline_min_duration_s
            if args.duration_seconds is None
            else args.duration_seconds
        )
    )
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.summary_output is not None:
        args.summary_output.parent.mkdir(parents=True, exist_ok=True)
        args.summary_output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0 if result["detector_result"] == args.expect_result else 2


if __name__ == "__main__":
    raise SystemExit(main())
