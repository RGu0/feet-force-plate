"""Tests for the development-only PTY frame-stream runner."""

from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import numpy as np

from client.device.development_simulator import (
    VIRTUAL_CH340_ENVIRONMENT_VARIABLE,
    VIRTUAL_CH340_HOST_PATH,
)
from client.device.protocol import DaoOneP4864Parser, ProtocolProfile
from client.device.serial_transport import SerialByteTransport
from scripts.run_dop4864_virtual_ch340 import FRAME_INTERVAL_SECONDS, socat_command


def test_runner_uses_fixed_endpoint_aliases_and_nominal_rate() -> None:
    command = socat_command()

    assert any("link=/tmp/ffp-dop4864-host" in argument for argument in command)
    assert any("link=/tmp/ffp-dop4864-device" in argument for argument in command)
    assert FRAME_INTERVAL_SECONDS == 1 / 20.7


def test_runner_stream_decodes_as_zero_48_by_64_frame(monkeypatch) -> None:
    monkeypatch.setenv(VIRTUAL_CH340_ENVIRONMENT_VARIABLE, "1")
    runner = subprocess.Popen(
        [sys.executable, "scripts/run_dop4864_virtual_ch340.py"],
        env=os.environ.copy(),
    )
    transport: SerialByteTransport | None = None
    try:
        deadline = time.monotonic() + 5.0
        while not Path(VIRTUAL_CH340_HOST_PATH).exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert Path(VIRTUAL_CH340_HOST_PATH).exists()
        transport = SerialByteTransport.open(
            VIRTUAL_CH340_HOST_PATH,
            baud_rate=1_000_000,
            data_bits=8,
            parity="N",
            stop_bits=1,
        )
        parser = DaoOneP4864Parser(
            ProtocolProfile.observed_compact_8bit(version="do-p4864/1")
        )
        frames = []
        while not frames and time.monotonic() < deadline:
            frames.extend(parser.feed(transport.read(4_096)))
        assert len(frames) == 1
        assert frames[0].values.shape == (48, 64)
        assert frames[0].values.dtype == np.dtype("uint8")
        assert not frames[0].values.any()
    finally:
        if transport is not None:
            transport.close()
        runner.send_signal(signal.SIGTERM)
        runner.wait(timeout=5.0)
