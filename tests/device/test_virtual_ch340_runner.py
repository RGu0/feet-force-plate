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
from client.startup_validation.models import ValidationOutcome
from client.startup_validation.serial_connector import SerialValidationConnector
from client.startup_validation.service import DeviceValidationService, ValidationRequest
from scripts import run_dop4864_virtual_ch340 as runner_module
from scripts.run_dop4864_virtual_ch340 import FRAME_INTERVAL_SECONDS, socat_command


def test_runner_uses_fixed_endpoint_aliases_and_nominal_rate() -> None:
    command = socat_command()

    assert any("link=/tmp/ffp-dop4864-host" in argument for argument in command)
    assert any("link=/tmp/ffp-dop4864-device" in argument for argument in command)
    assert FRAME_INTERVAL_SECONDS == 1 / 20.7


def test_runner_reschedules_after_a_delayed_write(monkeypatch) -> None:
    clock = [0.0]
    sleeps: list[float] = []

    monkeypatch.setattr(runner_module.os, "open", lambda *_args: 7)
    monkeypatch.setattr(runner_module.os, "close", lambda _descriptor: None)
    monkeypatch.setattr(
        runner_module.os,
        "write",
        lambda _descriptor, _frame: clock.__setitem__(0, 1.0),
    )
    monkeypatch.setattr(runner_module.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(runner_module.time, "sleep", sleeps.append)

    runner_module._stream_zero_frames(duration_seconds=0.1)

    assert sleeps == [FRAME_INTERVAL_SECONDS]


def test_runner_stream_decodes_as_controlled_empty_48_by_64_frame(monkeypatch) -> None:
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
        while len(frames) < 2 and time.monotonic() < deadline:
            frames.extend(parser.feed(transport.read(4_096)))
        assert len(frames) >= 2
        assert frames[0].values.shape == (48, 64)
        assert frames[0].values.dtype == np.dtype("uint8")
        assert int(frames[0].values.max()) <= 1
        assert not np.array_equal(frames[0].values, frames[1].values)
    finally:
        if transport is not None:
            transport.close()
        runner.send_signal(signal.SIGTERM)
        runner.wait(timeout=5.0)


def test_runner_passes_production_startup_validation_with_development_switch(
    monkeypatch,
) -> None:
    monkeypatch.setenv(VIRTUAL_CH340_ENVIRONMENT_VARIABLE, "1")
    runner = subprocess.Popen(
        [sys.executable, "scripts/run_dop4864_virtual_ch340.py"],
        env=os.environ.copy(),
    )
    try:
        deadline = time.monotonic() + 5.0
        while not Path(VIRTUAL_CH340_HOST_PATH).exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert Path(VIRTUAL_CH340_HOST_PATH).exists()
        connection = SerialValidationConnector().connect()
        run = DeviceValidationService(
            transport=connection.transport,
            parser=connection.parser,
        ).run(
            ValidationRequest(
                terminal_id="development-test",
                device_ref="virtual-ch340",
                app_version="test",
            )
        )
        assert run.outcome is ValidationOutcome.PASS
    finally:
        runner.send_signal(signal.SIGTERM)
        runner.wait(timeout=5.0)
