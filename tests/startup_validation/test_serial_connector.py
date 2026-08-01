from __future__ import annotations

import pytest

from client.hardware_standardization.runtime import (
    HardwareConnectionUnavailable,
    HardwareStartupConnection,
)
from client.startup_validation.serial_connector import SerialValidationConnector
from client.startup_validation.workflow import DeviceBusy, DeviceNotFound


class _Transport:
    def read(self, _max_bytes: int) -> bytes:
        return b""

    def close(self) -> None:
        pass


def _connection(*, identity: str | None = None) -> HardwareStartupConnection:
    return HardwareStartupConnection(
        device_ref="hardware-opaque-1",
        transport=_Transport(),
        parser=object(),
        hardware_identity=identity,
    )


def test_connector_opens_available_ch340_and_returns_production_boundaries() -> None:
    connector = SerialValidationConnector(
        connection_factory=_connection,
    )

    connection = connector.connect()

    assert connection.device_ref.startswith("hardware-")
    assert "/dev/" not in connection.device_ref
    assert connection.hardware_identity is None


def test_connector_exposes_only_serial_backed_hardware_identity() -> None:
    connector = SerialValidationConnector(
        connection_factory=lambda: _connection(identity="opaque-hardware-identity"),
    )

    connection = connector.connect()

    assert connection.hardware_identity is not None
    assert connection.hardware_identity == "opaque-hardware-identity"


def test_connector_distinguishes_absent_from_busy_without_exposing_port() -> None:
    absent = SerialValidationConnector(
        connection_factory=lambda: (_ for _ in ()).throw(
            HardwareConnectionUnavailable("NOT_FOUND", "not found")
        )
    )
    busy = SerialValidationConnector(
        connection_factory=lambda: (_ for _ in ()).throw(
            HardwareConnectionUnavailable("BUSY", "busy")
        )
    )

    with pytest.raises(DeviceNotFound):
        absent.connect()
    with pytest.raises(DeviceBusy) as captured:
        busy.connect()

    assert "busy" not in str(captured.value)


def test_open_race_is_reported_as_busy_and_keeps_device_identity_private() -> None:
    connector = SerialValidationConnector(
        connection_factory=lambda: (_ for _ in ()).throw(
            HardwareConnectionUnavailable("BUSY", "denied")
        ),
    )

    with pytest.raises(DeviceBusy) as captured:
        connector.connect()

    assert "/dev/" not in str(captured.value)
