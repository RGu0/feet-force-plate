"""Activation-time DO-P4864 connection readiness, independent of identity."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum

from client.device.serial_transport import (
    PortAvailability,
    SerialPortCandidate,
    enumerate_ch340_ports,
)
from client.hardware_standardization.do_p4864 import DoP4864StandardizationAdapter


class ActivationHardwareStatus(StrEnum):
    READY = "READY"
    NOT_FOUND = "NOT_FOUND"
    BUSY = "BUSY"
    MULTIPLE_DEVICES = "MULTIPLE_DEVICES"


@dataclass(frozen=True, slots=True)
class ActivationHardwareResult:
    status: ActivationHardwareStatus


def _enumerate_active_dop4864_ports() -> Sequence[SerialPortCandidate]:
    specification = DoP4864StandardizationAdapter.observed_compact_8bit().specification
    return enumerate_ch340_ports(
        baud_rate=specification.serial_baud_rate,
        data_bits=specification.serial_data_bits,
        parity=specification.serial_parity,
        stop_bits=specification.serial_stop_bits,
    )


class ActivationHardwareConnectionProvider:
    """Find exactly one available DO-P4864 without treating USB metadata as ID."""

    def __init__(
        self,
        *,
        enumerate_ports: Callable[[], Sequence[SerialPortCandidate]] = _enumerate_active_dop4864_ports,
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
        return ActivationHardwareResult(ActivationHardwareStatus.READY)


# Kept as a source-compatible alias for integrations built before asset labels
# became the binding authority.  It now only reports connection readiness.
ActivationHardwareIdentityProvider = ActivationHardwareConnectionProvider


__all__ = [
    "ActivationHardwareConnectionProvider",
    "ActivationHardwareIdentityProvider",
    "ActivationHardwareResult",
    "ActivationHardwareStatus",
]
