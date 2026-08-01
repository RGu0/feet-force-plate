"""CH340 discovery and lazy pyserial adapter for DO-P4864 acquisition."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import os
from typing import Any, Callable, Iterable

from .transport import TransportDisconnected


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
    serial_number: str | None = None


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


def _serial_options(
    device: str,
    timeout_seconds: float,
    *,
    baud_rate: int,
    data_bits: int,
    parity: str,
    stop_bits: int,
) -> dict[str, Any]:
    options: dict[str, Any] = {
        "port": device,
        "baudrate": baud_rate,
        "bytesize": data_bits,
        "parity": parity,
        "stopbits": stop_bits,
        "timeout": timeout_seconds,
    }
    # POSIX serial devices may otherwise permit concurrent opens.  Both the
    # availability probe and normal acquisition request exclusive ownership so
    # another process cannot make a busy physical device look available.
    # pyserial supports this option on POSIX only; Windows COM ports are
    # already exclusively opened by the OS.
    if os.name == "posix":
        options["exclusive"] = True
    return options


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
    baud_rate: int,
    data_bits: int,
    parity: str,
    stop_bits: int,
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
                handle = serial_factory(
                    **_serial_options(
                        port.device,
                        0.0,
                        baud_rate=baud_rate,
                        data_bits=data_bits,
                        parity=parity,
                        stop_bits=stop_bits,
                    )
                )
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
                serial_number=(
                    str(getattr(port, "serial_number", "") or "").strip() or None
                ),
            )
        )
    return sorted(candidates, key=lambda item: item.device)


def stable_hardware_identity(candidate: SerialPortCandidate) -> str | None:
    """Return an opaque physical-device identity only when USB supplies a serial.

    A path, USB location, VID or PID alone identifies a host connection or model,
    not the physical board.  They therefore must not be used to partition a
    dynamic defect mask or to restore an engineering-selected device.
    """

    serial_number = (candidate.serial_number or "").strip()
    if not serial_number:
        return None
    material = f"{candidate.vid}:{candidate.pid}:{serial_number}".encode("utf-8")
    return f"usb-serial-{hashlib.sha256(material).hexdigest()[:20]}"


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
        baud_rate: int,
        data_bits: int,
        parity: str,
        stop_bits: int,
    ) -> SerialByteTransport:
        if not device:
            raise ValueError("device is required")
        if timeout_seconds < 0:
            raise ValueError("timeout_seconds cannot be negative")
        try:
            handle = serial_factory(
                **_serial_options(
                    device,
                    timeout_seconds,
                    baud_rate=baud_rate,
                    data_bits=data_bits,
                    parity=parity,
                    stop_bits=stop_bits,
                )
            )
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
