"""Activation-only discovery of a serial-backed physical hardware identity."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum

from client.device.serial_transport import (
    PortAvailability,
    SerialPortCandidate,
    enumerate_ch340_ports,
    stable_hardware_identity,
)


class ActivationHardwareStatus(StrEnum):
    READY = "READY"
    NOT_FOUND = "NOT_FOUND"
    BUSY = "BUSY"
    IDENTITY_UNAVAILABLE = "IDENTITY_UNAVAILABLE"
    MULTIPLE_DEVICES = "MULTIPLE_DEVICES"


@dataclass(frozen=True, slots=True)
class ActivationHardwareResult:
    status: ActivationHardwareStatus
    hardware_id: str | None = None

    @property
    def display_suffix(self) -> str | None:
        if self.hardware_id is None:
            return None
        return self.hardware_id[-6:]


class ActivationHardwareIdentityProvider:
    """Find exactly one available device without starting an acquisition."""

    def __init__(
        self,
        *,
        enumerate_ports: Callable[[], Sequence[SerialPortCandidate]] = (
            enumerate_ch340_ports
        ),
    ) -> None:
        self._enumerate_ports = enumerate_ports

    def discover(self) -> ActivationHardwareResult:
        try:
            candidates = tuple(self._enumerate_ports())
        except Exception:
            return ActivationHardwareResult(ActivationHardwareStatus.NOT_FOUND)
        if not candidates:
            return ActivationHardwareResult(ActivationHardwareStatus.NOT_FOUND)
        available = tuple(
            candidate
            for candidate in candidates
            if candidate.availability is PortAvailability.AVAILABLE
        )
        if not available:
            return ActivationHardwareResult(ActivationHardwareStatus.BUSY)
        if len(available) > 1:
            return ActivationHardwareResult(ActivationHardwareStatus.MULTIPLE_DEVICES)
        hardware_id = stable_hardware_identity(available[0])
        if hardware_id is None:
            return ActivationHardwareResult(
                ActivationHardwareStatus.IDENTITY_UNAVAILABLE
            )
        return ActivationHardwareResult(
            ActivationHardwareStatus.READY,
            hardware_id,
        )


__all__ = [
    "ActivationHardwareIdentityProvider",
    "ActivationHardwareResult",
    "ActivationHardwareStatus",
]
