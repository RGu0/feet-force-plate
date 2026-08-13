"""Run a development-only PTY-backed CH340 / DO-P4864 zero-frame stream."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from client.device.development_simulator import (
    VIRTUAL_CH340_DEVICE_PATH,
    VIRTUAL_CH340_HOST_PATH,
    make_zero_frame,
)


FRAME_INTERVAL_SECONDS = 1 / 20.7
ENDPOINT_WAIT_SECONDS = 5.0


def socat_command() -> list[str]:
    """Build the fixed PTY-pair command used by the development simulator."""

    return [
        "socat",
        "-d",
        "-d",
        f"pty,raw,echo=0,link={VIRTUAL_CH340_DEVICE_PATH}",
        f"pty,raw,echo=0,link={VIRTUAL_CH340_HOST_PATH}",
    ]


def _wait_for_endpoints(*, deadline: float) -> None:
    endpoints = (Path(VIRTUAL_CH340_DEVICE_PATH), Path(VIRTUAL_CH340_HOST_PATH))
    while time.monotonic() < deadline:
        if all(endpoint.exists() for endpoint in endpoints):
            return
        time.sleep(0.02)
    missing = ", ".join(str(endpoint) for endpoint in endpoints if not endpoint.exists())
    raise RuntimeError(f"virtual CH340 endpoints did not appear: {missing}")


def _stream_zero_frames(*, duration_seconds: float | None = None) -> None:
    frame = make_zero_frame()
    deadline = (
        None if duration_seconds is None else time.monotonic() + duration_seconds
    )
    next_frame_at = time.monotonic()
    descriptor = os.open(VIRTUAL_CH340_DEVICE_PATH, os.O_WRONLY | os.O_NOCTTY)
    try:
        while deadline is None or time.monotonic() < deadline:
            os.write(descriptor, frame)
            next_frame_at += FRAME_INTERVAL_SECONDS
            time.sleep(max(0.0, next_frame_at - time.monotonic()))
    finally:
        os.close(descriptor)


def run(*, duration_seconds: float | None = None) -> None:
    """Create the PTY pair and emit frames until interrupted or duration ends."""

    if shutil.which("socat") is None:
        raise RuntimeError("socat is required for the development virtual CH340")
    process = subprocess.Popen(socat_command())
    try:
        _wait_for_endpoints(deadline=time.monotonic() + ENDPOINT_WAIT_SECONDS)
        _stream_zero_frames(duration_seconds=duration_seconds)
    finally:
        process.terminate()
        try:
            process.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--duration-seconds",
        type=float,
        default=None,
        help="stop automatically after this positive duration; default streams until interrupted",
    )
    args = parser.parse_args()
    if args.duration_seconds is not None and args.duration_seconds <= 0:
        parser.error("--duration-seconds must be positive")
    try:
        run(duration_seconds=args.duration_seconds)
    except (OSError, RuntimeError) as exc:
        print(f"virtual CH340 simulator failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
