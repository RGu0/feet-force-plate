"""Transport port shared by physical serial and simulated devices."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


class TransportDisconnected(ConnectionError):
    """The byte source disconnected while acquisition was active."""


@runtime_checkable
class ByteTransport(Protocol):
    """Minimal blocking byte source used by the acquisition worker."""

    def read(self, max_bytes: int) -> bytes: ...

    def close(self) -> None: ...
