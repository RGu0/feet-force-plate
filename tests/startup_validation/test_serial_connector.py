from __future__ import annotations

import pytest

from client.device.protocol import ProfileEvidence
from client.device.serial_transport import PortAvailability, SerialPortCandidate
from client.startup_validation.serial_connector import SerialValidationConnector
from client.startup_validation.workflow import DeviceBusy, DeviceNotFound


class _Transport:
    def read(self, _max_bytes: int) -> bytes:
        return b""

    def close(self) -> None:
        pass


def _candidate(
    device: str,
    availability: PortAvailability,
) -> SerialPortCandidate:
    return SerialPortCandidate(
        device=device,
        vid=0x1A86,
        pid=0x7523,
        description="USB Serial",
        hwid="opaque",
        availability=availability,
    )


def test_connector_opens_available_ch340_and_returns_production_boundaries() -> None:
    opened: list[str] = []
    connector = SerialValidationConnector(
        enumerate_ports=lambda: [
            _candidate("/dev/cu.private-path", PortAvailability.AVAILABLE)
        ],
        transport_open=lambda device: opened.append(device) or _Transport(),
    )

    connection = connector.connect()

    assert opened == ["/dev/cu.private-path"]
    assert connection.device_ref.startswith("ch340-")
    assert "/dev/" not in connection.device_ref
    assert connection.parser.profile.evidence is ProfileEvidence.CAPTURE_VERIFIED
    assert connection.parser.profile.version == "do-p4864-observed-compact-8bit/1"


def test_connector_distinguishes_absent_from_busy_without_exposing_port() -> None:
    absent = SerialValidationConnector(enumerate_ports=lambda: [])
    busy = SerialValidationConnector(
        enumerate_ports=lambda: [
            _candidate("COM7", PortAvailability.BUSY_OR_UNAVAILABLE)
        ]
    )

    with pytest.raises(DeviceNotFound):
        absent.connect()
    with pytest.raises(DeviceBusy) as captured:
        busy.connect()

    assert "COM7" not in str(captured.value)


def test_open_race_is_reported_as_busy_and_keeps_device_identity_private() -> None:
    connector = SerialValidationConnector(
        enumerate_ports=lambda: [
            _candidate("/dev/cu.private-path", PortAvailability.AVAILABLE)
        ],
        transport_open=lambda _device: (_ for _ in ()).throw(OSError("denied")),
    )

    with pytest.raises(DeviceBusy) as captured:
        connector.connect()

    assert "/dev/" not in str(captured.value)
