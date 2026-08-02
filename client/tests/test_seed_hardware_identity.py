from __future__ import annotations

import pytest

from client.cloud.hardware_identity import (
    ActivationHardwareIdentityProvider,
    ActivationHardwareStatus,
)
from client.device.serial_transport import (
    PortAvailability,
    SerialPortCandidate,
    stable_hardware_identity,
)
from client.hardware_standardization.runtime import HardwareRuntime
from client.startup_validation.serial_connector import SerialValidationConnector
from client.startup_validation.workflow import DeviceIdentityMismatch


class MemoryTransport:
    def read(self, _max_bytes: int) -> bytes:
        return b""

    def close(self) -> None:
        pass


def candidate(
    device: str,
    *,
    serial_number: str | None,
    availability: PortAvailability = PortAvailability.AVAILABLE,
) -> SerialPortCandidate:
    return SerialPortCandidate(
        device=device,
        vid=0x1A86,
        pid=0x7523,
        description="USB Serial",
        hwid="VID:PID=1A86:7523",
        availability=availability,
        serial_number=serial_number,
    )


def test_activation_identity_requires_usb_serial_number() -> None:
    path_only = candidate("/dev/cu.usbserial-1410", serial_number=None)
    result = ActivationHardwareIdentityProvider(
        enumerate_ports=lambda: [path_only]
    ).discover()

    assert stable_hardware_identity(path_only) is None
    assert result.status is ActivationHardwareStatus.IDENTITY_UNAVAILABLE
    assert result.hardware_id is None


def test_activation_identity_reports_absent_busy_and_multiple_explicitly() -> None:
    absent = ActivationHardwareIdentityProvider(enumerate_ports=lambda: []).discover()
    busy = ActivationHardwareIdentityProvider(
        enumerate_ports=lambda: [
            candidate(
                "COM7",
                serial_number="board-7",
                availability=PortAvailability.BUSY_OR_UNAVAILABLE,
            )
        ]
    ).discover()
    multiple = ActivationHardwareIdentityProvider(
        enumerate_ports=lambda: [
            candidate("COM7", serial_number="board-7"),
            candidate("COM8", serial_number="board-8"),
        ]
    ).discover()

    assert absent.status is ActivationHardwareStatus.NOT_FOUND
    assert busy.status is ActivationHardwareStatus.BUSY
    assert multiple.status is ActivationHardwareStatus.MULTIPLE_DEVICES


def test_activation_returns_opaque_identity_and_suffix_only() -> None:
    device = candidate("/dev/cu.private", serial_number="board-serial-secret")
    result = ActivationHardwareIdentityProvider(
        enumerate_ports=lambda: [device]
    ).discover()

    assert result.status is ActivationHardwareStatus.READY
    assert result.hardware_id is not None
    assert result.hardware_id.startswith("usb-serial-")
    assert "board-serial-secret" not in result.hardware_id
    assert result.display_suffix == result.hardware_id[-6:]


def test_startup_opens_only_the_license_bound_device() -> None:
    wrong = candidate("/dev/cu.wrong", serial_number="wrong-board")
    expected = candidate("/dev/cu.expected", serial_number="expected-board")
    expected_id = stable_hardware_identity(expected)
    assert expected_id is not None
    opened: list[str] = []
    runtime = HardwareRuntime(
        enumerate_ports=lambda **_options: [wrong, expected],
        transport_open=lambda device, **_options: opened.append(device)
        or MemoryTransport(),
    )
    connector = SerialValidationConnector(
        runtime=runtime,
        expected_hardware_identity=expected_id,
    )

    connection = connector.connect()

    assert opened == [expected.device]
    assert connection.hardware_identity == expected_id


def test_startup_rejects_mismatched_physical_device_before_opening() -> None:
    wrong = candidate("/dev/cu.wrong", serial_number="wrong-board")
    opened: list[str] = []
    runtime = HardwareRuntime(
        enumerate_ports=lambda **_options: [wrong],
        transport_open=lambda device, **_options: opened.append(device)
        or MemoryTransport(),
    )
    connector = SerialValidationConnector(
        runtime=runtime,
        expected_hardware_identity="usb-serial-0123456789abcdef0123",
    )

    with pytest.raises(DeviceIdentityMismatch) as caught:
        connector.connect()

    assert opened == []
    assert wrong.device not in str(caught.value)
    assert wrong.serial_number not in str(caught.value)
