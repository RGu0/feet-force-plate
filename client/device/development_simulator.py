"""Development-only virtual CH340 and DO-P4864 frame contracts.

This module makes no claim to create a USB device.  It supplies app-layer
metadata and exact byte frames for a PTY-backed local simulator.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from .serial_transport import PortAvailability, SerialPortCandidate


VIRTUAL_CH340_ENVIRONMENT_VARIABLE = "FEETFORCEPLATE_DEVELOPMENT_VIRTUAL_CH340"
VIRTUAL_CH340_HOST_PATH = "/tmp/ffp-dop4864-host"
VIRTUAL_CH340_DEVICE_PATH = "/tmp/ffp-dop4864-device"
VIRTUAL_CH340_DESCRIPTION = "USB-Enhanced-SERIAL CH340 (simulated)"
VIRTUAL_CH340_PTY_BAUD_RATE = 115_200


def virtual_ch340_enabled(environ: Mapping[str, str] | None = None) -> bool:
    """Return true only for the explicit development simulator switch."""

    values = os.environ if environ is None else environ
    return values.get(VIRTUAL_CH340_ENVIRONMENT_VARIABLE) == "1"


def make_controlled_empty_frame(frame_index: int) -> bytes:
    """Return a low-amplitude empty-board frame for development validation.

    A single source cell alternates between 0 and 1.  It remains far below the
    empty-board load threshold while avoiding a synthetic constant signal.
    """

    if frame_index < 0:
        raise ValueError("frame_index must be non-negative")
    payload = bytearray(3_072)
    payload[0] = frame_index % 2
    return b"\xff\xaa\x0c\x07\x01" + bytes(payload) + b"\x00\xfa"


def make_zero_frame() -> bytes:
    """Return the historical all-zero development protocol fixture."""

    return b"\xff\xaa\x0c\x07\x01" + (b"\x00" * 3_072) + b"\x00\xfa"


def virtual_ch340_candidate() -> SerialPortCandidate:
    """Return development metadata without asserting physical USB identity."""

    return SerialPortCandidate(
        device=VIRTUAL_CH340_HOST_PATH,
        vid=0x1A86,
        pid=0x7523,
        description=VIRTUAL_CH340_DESCRIPTION,
        hwid="DEVELOPMENT-VIRTUAL-CH340",
        availability=PortAvailability.UNKNOWN,
        serial_number=None,
    )


def uses_virtual_ch340_host(device: str) -> bool:
    """Identify the explicit development PTY without matching arbitrary paths."""

    return virtual_ch340_enabled() and device == VIRTUAL_CH340_HOST_PATH
