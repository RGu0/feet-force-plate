"""Development-only virtual CH340 contract tests."""

from __future__ import annotations

from client.device.development_simulator import (
    VIRTUAL_CH340_ENVIRONMENT_VARIABLE,
    VIRTUAL_CH340_HOST_PATH,
    make_controlled_empty_frame,
    make_zero_frame,
    virtual_ch340_candidate,
    virtual_ch340_enabled,
)
from client.device.serial_transport import PortAvailability, enumerate_ch340_ports
from client.device.serial_transport import SerialByteTransport


def test_zero_frame_matches_observed_compact_protocol() -> None:
    frame = make_zero_frame()

    assert len(frame) == 3_079
    assert frame[:5] == bytes.fromhex("FF AA 0C 07 01")
    assert frame[5:3_077] == b"\x00" * 3_072
    assert frame[3_077:] == bytes.fromhex("00 FA")


def test_controlled_empty_frames_are_low_amplitude_and_vary() -> None:
    first = make_controlled_empty_frame(0)
    second = make_controlled_empty_frame(1)

    assert len(first) == len(second) == 3_079
    assert first[:5] == second[:5] == bytes.fromhex("FF AA 0C 07 01")
    assert first[5:3_077] == b"\x00" * 3_072
    assert second[5] == 1
    assert second[6:3_077] == b"\x00" * 3_071
    assert first[3_077:] == second[3_077:] == bytes.fromhex("00 FA")


def test_simulated_candidate_declares_generic_ch340_metadata() -> None:
    candidate = virtual_ch340_candidate()

    assert candidate.device == VIRTUAL_CH340_HOST_PATH
    assert (candidate.vid, candidate.pid) == (0x1A86, 0x7523)
    assert candidate.serial_number is None
    assert candidate.description == "USB-Enhanced-SERIAL CH340 (simulated)"


def test_virtual_ch340_requires_exact_explicit_environment_switch() -> None:
    assert not virtual_ch340_enabled({})
    assert not virtual_ch340_enabled({VIRTUAL_CH340_ENVIRONMENT_VARIABLE: "true"})
    assert virtual_ch340_enabled({VIRTUAL_CH340_ENVIRONMENT_VARIABLE: "1"})


def test_enumeration_injects_simulated_candidate_only_when_explicitly_enabled(
    monkeypatch,
) -> None:
    options = {
        "port_provider": lambda: (),
        "probe_availability": False,
        "baud_rate": 1_000_000,
        "data_bits": 8,
        "parity": "N",
        "stop_bits": 1,
    }

    assert enumerate_ch340_ports(**options) == []

    monkeypatch.setenv(VIRTUAL_CH340_ENVIRONMENT_VARIABLE, "1")
    candidates = enumerate_ch340_ports(**options)

    assert [(item.device, item.vid, item.pid) for item in candidates] == [
        (VIRTUAL_CH340_HOST_PATH, 0x1A86, 0x7523)
    ]
    assert candidates[0].availability is PortAvailability.UNKNOWN


def test_virtual_host_uses_pty_compatible_baud_rate_only_in_development_mode(
    monkeypatch,
) -> None:
    calls = []

    class Handle:
        reset_calls = 0

        def reset_input_buffer(self) -> None:
            self.reset_calls += 1

        def close(self) -> None:
            return None

    monkeypatch.setenv(VIRTUAL_CH340_ENVIRONMENT_VARIABLE, "1")
    transport = SerialByteTransport.open(
        VIRTUAL_CH340_HOST_PATH,
        serial_factory=lambda **kwargs: calls.append(kwargs) or Handle(),
        baud_rate=1_000_000,
        data_bits=8,
        parity="N",
        stop_bits=1,
    )

    assert calls[0]["baudrate"] == 115_200
    assert transport._serial.reset_calls == 1
    transport.close()


def test_virtual_candidate_probe_uses_pty_compatible_baud_rate(monkeypatch) -> None:
    calls = []

    class Handle:
        def close(self) -> None:
            return None

    monkeypatch.setenv(VIRTUAL_CH340_ENVIRONMENT_VARIABLE, "1")
    candidates = enumerate_ch340_ports(
        port_provider=lambda: (),
        serial_factory=lambda **kwargs: calls.append(kwargs) or Handle(),
        probe_availability=True,
        baud_rate=1_000_000,
        data_bits=8,
        parity="N",
        stop_bits=1,
    )

    assert candidates[0].availability is PortAvailability.AVAILABLE
    assert calls[0]["baudrate"] == 115_200
