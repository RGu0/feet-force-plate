"""Tests for the development-only PTY frame-stream runner."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import numpy as np
import pytest

from client.device.development_simulator import (
    VIRTUAL_CH340_DEVICE_PATH,
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


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _run_runner_from_repository(monkeypatch) -> None:
    """Let the runner script import ``client`` however pytest was launched."""

    inherited = os.environ.get("PYTHONPATH")
    monkeypatch.setenv(
        "PYTHONPATH",
        os.pathsep.join([str(PROJECT_ROOT), *([inherited] if inherited else [])]),
    )
    monkeypatch.chdir(PROJECT_ROOT)


def _process_group_alive(group_id: int) -> bool:
    try:
        os.killpg(group_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


@contextmanager
def _running_runner(monkeypatch) -> Iterator[subprocess.Popen]:
    """Run the runner in its own session and reap the whole group on exit.

    The runner's ``socat`` child shares that session's process group, so the
    group-wide TERM-then-KILL below cannot orphan it even when the runner hangs
    or dies before its own cleanup runs.
    """

    monkeypatch.setenv(VIRTUAL_CH340_ENVIRONMENT_VARIABLE, "1")
    _run_runner_from_repository(monkeypatch)
    runner = subprocess.Popen(
        [sys.executable, "scripts/run_dop4864_virtual_ch340.py"],
        env=os.environ.copy(),
        start_new_session=True,
    )
    try:
        yield runner
    finally:
        group_id = runner.pid
        # Let the runner stop its own socat first: signalling socat as well
        # would cut its cleanup short and strand the endpoint aliases.
        if runner.poll() is None:
            runner.send_signal(signal.SIGTERM)
            try:
                runner.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                pass
        # Whatever is left was orphaned; TERM lets socat still unlink aliases.
        if _process_group_alive(group_id):
            os.killpg(group_id, signal.SIGTERM)
        deadline = time.monotonic() + 5.0
        while _process_group_alive(group_id) and time.monotonic() < deadline:
            runner.poll()
            time.sleep(0.02)
        try:
            os.killpg(group_id, signal.SIGKILL)
        except ProcessLookupError:
            pass
        runner.wait()


def _wait_for_host_endpoint(deadline: float) -> None:
    while not Path(VIRTUAL_CH340_HOST_PATH).exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert Path(VIRTUAL_CH340_HOST_PATH).exists()


def _assert_no_endpoint_aliases() -> None:
    for endpoint in (VIRTUAL_CH340_DEVICE_PATH, VIRTUAL_CH340_HOST_PATH):
        assert not Path(endpoint).is_symlink(), f"{endpoint} outlived the runner"


def test_runner_uses_fixed_endpoint_aliases_and_nominal_rate() -> None:
    command = socat_command()

    assert any("link=/tmp/ffp-dop4864-host" in argument for argument in command)
    assert any("link=/tmp/ffp-dop4864-device" in argument for argument in command)
    assert FRAME_INTERVAL_SECONDS == 1 / 20.7


@pytest.mark.skipif(os.name == "nt", reason="PTY runner requires POSIX O_NOCTTY")
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


@pytest.mark.skipif(os.name == "nt", reason="PTY runner requires POSIX socat")
def test_runner_reaps_socat_when_terminated(monkeypatch) -> None:
    with _running_runner(monkeypatch) as runner:
        _wait_for_host_endpoint(time.monotonic() + 5.0)
        assert _process_group_alive(runner.pid)

        # Signal only the runner, as an operator or a test teardown would; its
        # socat child must not outlive it.
        runner.send_signal(signal.SIGTERM)
        runner.wait(timeout=5.0)

        assert not _process_group_alive(runner.pid), "socat outlived the runner"
        _assert_no_endpoint_aliases()


@pytest.mark.skipif(os.name == "nt", reason="PTY runner requires POSIX socat")
def test_runner_cleans_up_when_its_whole_group_is_signalled(monkeypatch) -> None:
    with _running_runner(monkeypatch) as runner:
        _wait_for_host_endpoint(time.monotonic() + 5.0)

        # A terminal Ctrl-C or a group kill reaches socat and the runner at once.
        os.killpg(runner.pid, signal.SIGTERM)
        runner.wait(timeout=5.0)

        assert not _process_group_alive(runner.pid), "socat outlived the runner"
        _assert_no_endpoint_aliases()


@pytest.mark.skipif(os.name == "nt", reason="PTY runner requires POSIX socat")
def test_runner_stream_decodes_as_controlled_empty_48_by_64_frame(monkeypatch) -> None:
    with _running_runner(monkeypatch):
        deadline = time.monotonic() + 5.0
        _wait_for_host_endpoint(deadline)
        transport = SerialByteTransport.open(
            VIRTUAL_CH340_HOST_PATH,
            baud_rate=1_000_000,
            data_bits=8,
            parity="N",
            stop_bits=1,
        )
        try:
            parser = DaoOneP4864Parser(
                ProtocolProfile.observed_compact_8bit(version="do-p4864/1")
            )
            frames = []
            while len(frames) < 2 and time.monotonic() < deadline:
                frames.extend(parser.feed(transport.read(4_096)))
        finally:
            transport.close()
        assert len(frames) >= 2
        assert frames[0].values.shape == (48, 64)
        assert frames[0].values.dtype == np.dtype("uint8")
        assert int(frames[0].values.max()) <= 1
        assert not np.array_equal(frames[0].values, frames[1].values)


@pytest.mark.skipif(os.name == "nt", reason="PTY runner requires POSIX socat")
@pytest.mark.skipif(
    sys.platform == "darwin" and os.environ.get("GITHUB_ACTIONS") == "true",
    reason=(
        "GitHub-hosted macOS VMs oversleep the 20.7 Hz cadence (about 8 Hz observed), "
        "so the production rate check cannot pass there; Linux CI and real Macs cover it"
    ),
)
def test_runner_passes_production_startup_validation_with_development_switch(
    monkeypatch,
) -> None:
    with _running_runner(monkeypatch):
        _wait_for_host_endpoint(time.monotonic() + 5.0)
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
        assert run.outcome is ValidationOutcome.PASS, (run.reason, run.statistics)
