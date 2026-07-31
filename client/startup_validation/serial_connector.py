from __future__ import annotations

from collections.abc import Callable, Sequence
import hashlib

from client.device.protocol import DaoOneP4864Parser, ProtocolProfile
from client.device.serial_transport import (
    PortAvailability,
    SerialByteTransport,
    SerialPortCandidate,
    enumerate_ch340_ports,
    stable_hardware_identity,
)
from client.device.transport import ByteTransport

from .workflow import DeviceBusy, DeviceNotFound, ValidationConnection


class SerialValidationConnector:
    """Open one production CH340 byte source for a startup validation attempt."""

    def __init__(
        self,
        *,
        enumerate_ports: Callable[[], Sequence[SerialPortCandidate]] = enumerate_ch340_ports,
        transport_open: Callable[[str], ByteTransport] = SerialByteTransport.open,
    ) -> None:
        self._enumerate_ports = enumerate_ports
        self._transport_open = transport_open

    def connect(self) -> ValidationConnection:
        try:
            candidates = tuple(self._enumerate_ports())
        except Exception as error:
            raise DeviceNotFound("supported pressure device discovery failed") from error
        available = tuple(
            candidate
            for candidate in candidates
            if candidate.availability is PortAvailability.AVAILABLE
        )
        if not available:
            if candidates:
                raise DeviceBusy("supported pressure device is unavailable")
            raise DeviceNotFound("supported pressure device was not found")

        candidate = available[0]
        try:
            transport = self._transport_open(candidate.device)
        except Exception as error:
            raise DeviceBusy("supported pressure device could not be opened") from error
        profile = ProtocolProfile.observed_compact_8bit(
            version="do-p4864-observed-compact-8bit/1"
        )
        parser = DaoOneP4864Parser(profile)
        return ValidationConnection(
            device_ref=_opaque_device_ref(candidate.device),
            transport=transport,
            parser=parser,
            hardware_identity=stable_hardware_identity(candidate),
        )


def _opaque_device_ref(device: str) -> str:
    digest = hashlib.sha256(device.encode("utf-8")).hexdigest()[:20]
    return f"ch340-{digest}"
