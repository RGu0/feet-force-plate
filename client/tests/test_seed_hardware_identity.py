from __future__ import annotations

from client.cloud.hardware_identity import (
    ActivationHardwareConnectionProvider,
    ActivationHardwareStatus,
)
from client.device.serial_transport import PortAvailability, SerialPortCandidate


def candidate(
    device: str, *, availability: PortAvailability = PortAvailability.AVAILABLE
) -> SerialPortCandidate:
    return SerialPortCandidate(
        device=device,
        vid=0x1A86,
        pid=0x7523,
        description="USB Serial",
        hwid="VID:PID=1A86:7523",
        availability=availability,
        serial_number=None,
    )


def test_serial_less_ch340_is_ready_for_asset_label_activation() -> None:
    result = ActivationHardwareConnectionProvider(
        enumerate_ports=lambda: [candidate("/dev/cu.usbserial-1410")]
    ).discover()

    assert result.status is ActivationHardwareStatus.READY
    assert not hasattr(result, "hardware_id")


def test_connection_provider_reports_absent_busy_and_multiple_explicitly() -> None:
    absent = ActivationHardwareConnectionProvider(enumerate_ports=lambda: []).discover()
    busy = ActivationHardwareConnectionProvider(
        enumerate_ports=lambda: [
            candidate("COM7", availability=PortAvailability.BUSY_OR_UNAVAILABLE)
        ]
    ).discover()
    multiple = ActivationHardwareConnectionProvider(
        enumerate_ports=lambda: [candidate("COM7"), candidate("COM8")]
    ).discover()

    assert absent.status is ActivationHardwareStatus.NOT_FOUND
    assert busy.status is ActivationHardwareStatus.BUSY
    assert multiple.status is ActivationHardwareStatus.MULTIPLE_DEVICES
