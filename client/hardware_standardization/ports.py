"""Stable contracts exposed by the hardware layer to application consumers.

These contracts deliberately describe a decoded observation only by its timing,
sequence and matrix payload.  They contain no device model, transport, parser,
calibration or quality-policy implementation detail.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np
from numpy.typing import NDArray

from client.device.session_ui import HardwareUiFailure, HardwareUiFailureCode


class DecodedHardwareFrame(Protocol):
    """One immutable observation already decoded by the hardware layer."""

    values: NDArray[np.number]
    source_index: int
    host_monotonic_ns: int


class LatestHardwareFramePort(Protocol):
    """Latest-only read port; it never transfers storage ownership."""

    def read(self) -> DecodedHardwareFrame | None: ...


@dataclass(frozen=True, slots=True)
class HardwareDisplayGeometry:
    """Device-neutral geometry and refresh information permitted in the UI."""

    rows: int
    columns: int
    width_mm: float
    height_mm: float
    maximum_refresh_hz: float

    def __post_init__(self) -> None:
        if self.rows <= 0 or self.columns <= 0:
            raise ValueError("display geometry dimensions must be positive")
        if self.width_mm <= 0 or self.height_mm <= 0:
            raise ValueError("display geometry physical dimensions must be positive")
        if self.maximum_refresh_hz <= 0:
            raise ValueError("display maximum refresh rate must be positive")

    @property
    def matrix_shape(self) -> tuple[int, int]:
        return (self.rows, self.columns)


__all__ = (
    "DecodedHardwareFrame",
    "HardwareDisplayGeometry",
    "HardwareUiFailure",
    "HardwareUiFailureCode",
    "LatestHardwareFramePort",
)
