"""CH340 discovery and lazy pyserial adapter for DO-P4864 acquisition."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Callable, Iterable

from .transport import TransportDisconnected


BAUD_RATE = 1_000_000
CH340_VENDOR_ID = 0x1A86


class PortAvailability(StrEnum):
    UNKNOWN = "UNKNOWN"
    AVAILABLE = "AVAILABLE"
    BUSY_OR_UNAVAILABLE = "BUSY_OR_UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class SerialPortCandidate:
    device: str
    vid: int | None
    pid: int | None
    description: str
    hwid: str
    availability: PortAvailability
    probe_error: str | None = None


def _default_port_provider() -> Iterable[Any]:
    try:
        from serial.tools import list_ports
    except ImportError as exc:
        raise RuntimeError("pyserial is required for physical CH340 discovery") from exc
    return list_ports.comports()


def _default_serial_factory(**kwargs: Any) -> Any:
    try:
        import serial
    except ImportError as exc:
        raise RuntimeError("pyserial is required for physical CH340 acquisition") from exc
    return serial.Serial(**kwargs)


def _serial_options(device: str, timeout_seconds: float) -> dict[str, Any]:
    return {
        "port": device,
        "baudrate": BAUD_RATE,
        "bytesize": 8,
        "parity": "N",
        "stopbits": 1,
        "timeout": timeout_seconds,
    }


def _is_ch340(port: Any) -> bool:
    if getattr(port, "vid", None) == CH340_VENDOR_ID:
        return True
    identity = " ".join(
        str(getattr(port, field, "") or "")
        for field in ("device", "description", "hwid")
    ).lower()
    return "ch340" in identity or "ch341" in identity


def enumerate_ch340_ports(
    *,
    port_provider: Callable[[], Iterable[Any]] = _default_port_provider,
    serial_factory: Callable[..., Any] = _default_serial_factory,
    probe_availability: bool = True,
) -> list[SerialPortCandidate]:
    """List CH340 candidates; failed probes are conservatively non-available."""

    candidates: list[SerialPortCandidate] = []
    for port in port_provider():
        if not _is_ch340(port):
            continue
        availability = PortAvailability.UNKNOWN
        probe_error: str | None = None
        if probe_availability:
            try:
                handle = serial_factory(**_serial_options(port.device, 0.0))
                handle.close()
                availability = PortAvailability.AVAILABLE
            except Exception as exc:
                availability = PortAvailability.BUSY_OR_UNAVAILABLE
                probe_error = f"{type(exc).__name__}: {exc}"
        candidates.append(
            SerialPortCandidate(
                device=str(port.device),
                vid=getattr(port, "vid", None),
                pid=getattr(port, "pid", None),
                description=str(getattr(port, "description", "") or ""),
                hwid=str(getattr(port, "hwid", "") or ""),
                availability=availability,
                probe_error=probe_error,
            )
        )
    return sorted(candidates, key=lambda item: item.device)


class SerialByteTransport:
    """Blocking byte transport around an already-open serial-compatible object."""

    def __init__(self, serial_handle: Any) -> None:
        self._serial = serial_handle
        self._closed = False

    @classmethod
    def open(
        cls,
        device: str,
        *,
        serial_factory: Callable[..., Any] = _default_serial_factory,
        timeout_seconds: float = 0.5,
    ) -> SerialByteTransport:
        if not device:
            raise ValueError("device is required")
        if timeout_seconds < 0:
            raise ValueError("timeout_seconds cannot be negative")
        try:
            handle = serial_factory(**_serial_options(device, timeout_seconds))
        except Exception as exc:
            raise TransportDisconnected(
                f"could not open serial device {device}: {type(exc).__name__}: {exc}"
            ) from exc
        return cls(handle)

    def read(self, max_bytes: int) -> bytes:
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        if self._closed:
            raise TransportDisconnected("serial transport is closed")
        try:
            return bytes(self._serial.read(max_bytes))
        except Exception as exc:
            raise TransportDisconnected(
                f"serial read failed: {type(exc).__name__}: {exc}"
            ) from exc

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._serial.close()
