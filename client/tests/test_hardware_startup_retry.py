from __future__ import annotations

from client.device.serial_transport import PortAvailability, SerialPortCandidate
from client.hardware_standardization.runtime import HardwareRuntime


def _available_candidate() -> SerialPortCandidate:
    return SerialPortCandidate(
        device="COM-TEST",
        vid=0x1A86,
        pid=0x7523,
        description="CH340 test device",
        hwid="USB\\VID_1A86&PID_7523",
        availability=PortAvailability.AVAILABLE,
    )


def test_connect_startup_retries_a_transient_serial_open_failure() -> None:
    attempts = 0
    pauses: list[float] = []
    transport = object()

    def open_transport(_device: str, **_options: object) -> object:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("port is still being released")
        return transport

    runtime = HardwareRuntime(
        enumerate_ports=lambda **_options: (_available_candidate(),),
        transport_open=open_transport,
        connection_open_attempts=3,
        retry_delay_seconds=0.15,
        sleep=pauses.append,
    )

    connection = runtime.connect_startup()

    assert connection.transport is transport
    assert attempts == 2
    assert pauses == [0.15]


def test_connect_capture_skips_the_probe_open_close_cycle() -> None:
    probes: list[bool] = []
    transport = object()

    def enumerate_ports(**options: object):
        probes.append(bool(options["probe_availability"]))
        return (
            SerialPortCandidate(
                device="COM-TEST",
                vid=0x1A86,
                pid=0x7523,
                description="CH340 test device",
                hwid="USB\\VID_1A86&PID_7523",
                availability=PortAvailability.UNKNOWN,
            ),
        )

    runtime = HardwareRuntime(
        enumerate_ports=enumerate_ports,
        transport_open=lambda _device, **_options: transport,
    )

    connection = runtime.connect_capture()

    assert connection.transport is transport
    assert probes == [False]
