"""Byte-level DO-P4864 simulator built on explicit synthetic profiles."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import math
from pathlib import Path
import random
import time
from typing import Callable, Mapping

import numpy as np

from .protocol import (
    CHECKSUM_OFFSET,
    FRAME_LENGTH,
    FUNCTION_CODE,
    HEADER,
    ProtocolProfile,
    TAIL,
)
from .transport import TransportDisconnected


class PressurePattern(StrEnum):
    """Synthetic patterns that describe only raw sensor counts."""

    STATIC = "STATIC"
    LEFT_BIAS = "LEFT_BIAS"
    RIGHT_BIAS = "RIGHT_BIAS"
    COP_SWAY = "COP_SWAY"


class FaultKind(StrEnum):
    """Wire-level faults supported by the synthetic transport."""

    NOISE_PREFIX = "NOISE_PREFIX"
    BAD_LENGTH = "BAD_LENGTH"
    BAD_CHECKSUM = "BAD_CHECKSUM"
    BAD_TAIL = "BAD_TAIL"
    TRUNCATE = "TRUNCATE"
    DISCONNECT = "DISCONNECT"


@dataclass(frozen=True, slots=True)
class FaultPlan:
    """Deterministic fault events keyed by zero-based generated frame index."""

    events: Mapping[int, tuple[FaultKind, ...]]
    noise_prefix: bytes = b"\x00\x13\x37"

    def apply(self, frame_index: int, wire_frame: bytes) -> bytes:
        events = self.events.get(frame_index, ())
        output = bytearray(wire_frame)
        if FaultKind.BAD_LENGTH in events:
            output[2:4] = b"\x00\x00"
        if FaultKind.BAD_CHECKSUM in events:
            output[CHECKSUM_OFFSET] ^= 0x01
        if FaultKind.BAD_TAIL in events:
            output[-1] = 0x00
        if FaultKind.TRUNCATE in events:
            del output[FRAME_LENGTH // 2 :]
        if FaultKind.NOISE_PREFIX in events:
            output[:0] = self.noise_prefix
        return bytes(output)

    def disconnects_at(self, frame_index: int) -> bool:
        return FaultKind.DISCONNECT in self.events.get(frame_index, ())


@dataclass(frozen=True, slots=True)
class PressureScene:
    """Deterministic two-foot raw-count generator without physical units."""

    peak_count: int = 220
    sway_period_frames: int = 120
    sway_columns: float = 3.0

    def __post_init__(self) -> None:
        if not 1 <= self.peak_count <= 255:
            raise ValueError("peak_count must be within the uint8 raw-byte range")
        if self.sway_period_frames <= 0:
            raise ValueError("sway_period_frames must be positive")
        if not 0.0 <= self.sway_columns <= 8.0:
            raise ValueError("sway_columns must be between 0 and 8")

    def frame(self, frame_index: int, pattern: PressurePattern) -> np.ndarray:
        rows, columns = np.indices((48, 64), dtype=np.float64)
        column_shift = 0.0
        if pattern is PressurePattern.COP_SWAY:
            column_shift = self.sway_columns * math.sin(
                2.0 * math.pi * frame_index / self.sway_period_frames
            )
        left = np.exp(
            -(
                ((rows - 24.0) / 13.0) ** 2
                + ((columns - (20.0 + column_shift)) / 4.5) ** 2
            )
        )
        right = np.exp(
            -(
                ((rows - 24.0) / 13.0) ** 2
                + ((columns - (44.0 + column_shift)) / 4.5) ** 2
            )
        )
        left_weight = 1.0
        right_weight = 1.0
        if pattern is PressurePattern.LEFT_BIAS:
            left_weight, right_weight = 1.0, 0.45
        elif pattern is PressurePattern.RIGHT_BIAS:
            left_weight, right_weight = 0.45, 1.0
        counts = np.rint(self.peak_count * (left_weight * left + right_weight * right))
        return np.clip(counts, 0, 255).astype(np.uint8)


def encode_frame(values: np.ndarray, profile: ProtocolProfile) -> bytes:
    """Encode one 48x64 matrix as physical columns, top to bottom."""

    matrix = np.asarray(values)
    if matrix.shape != (48, 64):
        raise ValueError("DO-P4864 matrices must have shape (48, 64)")
    if np.any(matrix < 0) or np.any(matrix > 255):
        raise ValueError("DO-P4864 synthetic raw bytes must stay within 0..255")
    payload = matrix.astype(np.uint8, copy=False).tobytes(order="F")
    frame = bytearray(HEADER)
    frame.extend(FRAME_LENGTH.to_bytes(2, profile.length_byte_order))
    frame.append(FUNCTION_CODE)
    frame.extend(payload)
    checksum = (-sum(frame[profile.checksum_start : profile.checksum_end])) & 0xFF
    frame.append(checksum)
    frame.append(TAIL)
    if len(frame) != FRAME_LENGTH or len(frame) - 2 != CHECKSUM_OFFSET:
        raise AssertionError("DO-P4864 simulator produced an invalid frame size")
    return bytes(frame)


class SyntheticP4864Transport:
    """Blocking byte transport that emits protocol frames, not decoded objects."""

    def __init__(
        self,
        profile: ProtocolProfile,
        *,
        frame_source: Callable[[int], np.ndarray] | None = None,
        pattern: PressurePattern = PressurePattern.STATIC,
        rate_hz: float = 12.0,
        baud_rate: int = 1_000_000,
        jitter_fraction: float = 0.0,
        realtime: bool = True,
        max_frames: int | None = None,
        random_seed: int = 82,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
        sleep: Callable[[float], None] = time.sleep,
        fault_plan: FaultPlan | None = None,
    ) -> None:
        if rate_hz <= 0:
            raise ValueError("rate_hz must be positive")
        if baud_rate <= 0:
            raise ValueError("baud_rate must be positive")
        if not 0.0 <= jitter_fraction <= 1.0:
            raise ValueError("jitter_fraction must be between 0 and 1")
        if max_frames is not None and max_frames < 0:
            raise ValueError("max_frames cannot be negative")
        self.profile = profile
        self.rate_hz = float(rate_hz)
        self.baud_rate = baud_rate
        self.jitter_fraction = jitter_fraction
        self.realtime = realtime
        self.max_frames = max_frames
        scene = PressureScene()
        self._frame_source = frame_source or (
            lambda frame_index: scene.frame(frame_index, pattern)
        )
        self._random = random.Random(random_seed)
        self._monotonic_ns = monotonic_ns
        self._sleep = sleep
        self._fault_plan = fault_plan or FaultPlan(events={})
        self._next_frame_at_ns: int | None = None
        self._frame_index = 0
        self._pending = bytearray()
        self._open = True
        self._disconnect_pending = False

    @property
    def exhausted(self) -> bool:
        return (
            self.max_frames is not None
            and self._frame_index >= self.max_frames
            and not self._pending
        )

    def read(self, max_bytes: int) -> bytes:
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        if not self._open:
            raise TransportDisconnected("synthetic transport is closed")
        while len(self._pending) < max_bytes and not self._generation_complete:
            if self._fault_plan.disconnects_at(self._frame_index):
                self._disconnect_pending = True
                break
            self._pace()
            wire_frame = encode_frame(
                self._frame_source(self._frame_index), self.profile
            )
            self._pending.extend(
                self._fault_plan.apply(self._frame_index, wire_frame)
            )
            self._frame_index += 1
        if not self._pending and self._disconnect_pending:
            self._open = False
            raise TransportDisconnected(
                f"synthetic disconnect before frame {self._frame_index}"
            )
        chunk = bytes(self._pending[:max_bytes])
        del self._pending[:max_bytes]
        return chunk

    def close(self) -> None:
        self._open = False

    @property
    def _generation_complete(self) -> bool:
        return self.max_frames is not None and self._frame_index >= self.max_frames

    def _pace(self) -> None:
        if not self.realtime:
            return
        now = self._monotonic_ns()
        if self._next_frame_at_ns is not None and now < self._next_frame_at_ns:
            self._sleep((self._next_frame_at_ns - now) / 1_000_000_000)
            now = self._next_frame_at_ns
        base_period_ns = 1_000_000_000 / self.rate_hz
        jitter = self._random.uniform(-self.jitter_fraction, self.jitter_fraction)
        self._next_frame_at_ns = int(now + base_period_ns * (1.0 + jitter))


class CaptureReplayTransport:
    """Digest-checked replay of raw serial bytes through the ByteTransport port."""

    def __init__(self, capture_bytes: bytes) -> None:
        self._capture_bytes = capture_bytes
        self._offset = 0
        self._open = True

    @classmethod
    def from_file(
        cls, path: str | Path, *, expected_sha256: str
    ) -> CaptureReplayTransport:
        capture_bytes = Path(path).read_bytes()
        observed = hashlib.sha256(capture_bytes).hexdigest()
        if observed != expected_sha256.lower():
            raise ValueError(
                f"capture SHA-256 mismatch: expected {expected_sha256.lower()}, got {observed}"
            )
        return cls(capture_bytes)

    @property
    def exhausted(self) -> bool:
        return self._offset >= len(self._capture_bytes)

    def read(self, max_bytes: int) -> bytes:
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        if not self._open:
            raise TransportDisconnected("capture replay transport is closed")
        chunk = self._capture_bytes[self._offset : self._offset + max_bytes]
        self._offset += len(chunk)
        return chunk

    def close(self) -> None:
        self._open = False
