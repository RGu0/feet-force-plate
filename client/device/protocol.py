"""DO-P4864 byte-stream protocol contracts.

The manual does not prove the wire byte order of the length field or the
CheckSum coverage range.  Those choices therefore live in an explicit profile
instead of being hidden parser assumptions.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import string
import time
from typing import Callable, Literal

import numpy as np


FRAME_LENGTH = 6_151
HEADER = b"\xff\xaa"
LENGTH_OFFSET = 2
FUNCTION_OFFSET = 4
PAYLOAD_OFFSET = 5
CHECKSUM_OFFSET = 6_149
TAIL_OFFSET = 6_150
FUNCTION_CODE = 0x01
TAIL = 0xFA


class ProfileEvidence(StrEnum):
    """Strength of evidence behind a protocol profile."""

    SYNTHETIC = "SYNTHETIC"
    CAPTURE_VERIFIED = "CAPTURE_VERIFIED"


class UnverifiedProtocolProfileError(ValueError):
    """Raised when unverified wire assumptions reach a production parser."""


@dataclass(frozen=True, slots=True)
class ProtocolProfile:
    """Versioned choices that must ultimately come from a serial fixture."""

    version: str
    length_byte_order: Literal["little", "big"]
    checksum_start: int
    checksum_end: int
    evidence: ProfileEvidence
    fixture_sha256: str | None = None

    def __post_init__(self) -> None:
        if self.length_byte_order not in ("little", "big"):
            raise ValueError("length_byte_order must be 'little' or 'big'")
        if not 0 <= self.checksum_start < self.checksum_end <= CHECKSUM_OFFSET:
            raise ValueError("CheckSum coverage must exclude the CheckSum byte")
        if self.evidence is ProfileEvidence.CAPTURE_VERIFIED:
            digest = (self.fixture_sha256 or "").lower()
            if len(digest) != 64 or any(char not in string.hexdigits for char in digest):
                raise ValueError(
                    "capture-verified profiles require a 64-character fixture SHA-256"
                )
            object.__setattr__(self, "fixture_sha256", digest)

    @classmethod
    def synthetic(
        cls,
        *,
        version: str,
        length_byte_order: Literal["little", "big"],
        checksum_start: int,
        checksum_end: int,
    ) -> ProtocolProfile:
        return cls(
            version=version,
            length_byte_order=length_byte_order,
            checksum_start=checksum_start,
            checksum_end=checksum_end,
            evidence=ProfileEvidence.SYNTHETIC,
        )

    @classmethod
    def capture_verified(
        cls,
        *,
        version: str,
        length_byte_order: Literal["little", "big"],
        checksum_start: int,
        checksum_end: int,
        fixture_sha256: str,
    ) -> ProtocolProfile:
        normalized_digest = fixture_sha256.lower()
        if len(normalized_digest) != 64 or any(
            char not in string.hexdigits for char in normalized_digest
        ):
            raise ValueError("fixture_sha256 must be a 64-character hexadecimal digest")
        return cls(
            version=version,
            length_byte_order=length_byte_order,
            checksum_start=checksum_start,
            checksum_end=checksum_end,
            evidence=ProfileEvidence.CAPTURE_VERIFIED,
            fixture_sha256=normalized_digest,
        )


@dataclass(frozen=True, slots=True)
class RawFrame:
    """A successfully decoded matrix with host-side audit fields."""

    values: np.ndarray
    host_monotonic_ns: int
    host_wall_time_ns: int
    source_index: int
    device_frame_seq: int | None
    device_timestamp_ns: int | None
    quality_flags: frozenset[str]


@dataclass(slots=True)
class ProtocolStatistics:
    """Bounded aggregate evidence about the host receive path."""

    bytes_received: int = 0
    valid_frames: int = 0
    invalid_frames: int = 0
    checksum_failures: int = 0
    length_failures: int = 0
    function_failures: int = 0
    tail_failures: int = 0
    resynchronizations: int = 0
    discarded_bytes: int = 0
    peak_buffer_bytes: int = 0
    interval_count: int = 0
    interval_min_ns: int | None = None
    interval_max_ns: int | None = None
    _interval_total_ns: int = 0
    _previous_monotonic_ns: int | None = None

    @property
    def interval_mean_ns(self) -> float | None:
        if not self.interval_count:
            return None
        return self._interval_total_ns / self.interval_count

    def record_valid_frame(self, monotonic_ns: int) -> None:
        if self._previous_monotonic_ns is not None:
            interval = monotonic_ns - self._previous_monotonic_ns
            self.interval_count += 1
            self._interval_total_ns += interval
            self.interval_min_ns = (
                interval if self.interval_min_ns is None else min(self.interval_min_ns, interval)
            )
            self.interval_max_ns = (
                interval if self.interval_max_ns is None else max(self.interval_max_ns, interval)
            )
        self._previous_monotonic_ns = monotonic_ns
        self.valid_frames += 1


class DaoOneP4864Parser:
    """Incremental DO-P4864 byte-stream parser."""

    def __init__(
        self,
        profile: ProtocolProfile,
        *,
        allow_unverified: bool = False,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
        wall_time_ns: Callable[[], int] = time.time_ns,
        max_buffer_bytes: int = FRAME_LENGTH * 2,
    ) -> None:
        if profile.evidence is not ProfileEvidence.CAPTURE_VERIFIED and not allow_unverified:
            raise UnverifiedProtocolProfileError(
                "DO-P4864 profile is not backed by a physical serial fixture"
            )
        if max_buffer_bytes < FRAME_LENGTH:
            raise ValueError(f"max_buffer_bytes must be at least {FRAME_LENGTH}")
        self.profile = profile
        self._monotonic_ns = monotonic_ns
        self._wall_time_ns = wall_time_ns
        self._buffer = bytearray()
        self._next_source_index = 0
        self._max_buffer_bytes = max_buffer_bytes
        self.statistics = ProtocolStatistics()

    @property
    def buffered_bytes(self) -> int:
        return len(self._buffer)

    def feed(self, chunk: bytes | bytearray | memoryview) -> list[RawFrame]:
        """Consume arbitrary byte chunks and return every complete valid frame."""

        view = memoryview(chunk)
        self.statistics.bytes_received += len(view)
        decoded: list[RawFrame] = []
        offset = 0
        while offset < len(view):
            capacity = self._max_buffer_bytes - len(self._buffer)
            if capacity <= 0:
                decoded.extend(self._drain_buffer())
                capacity = self._max_buffer_bytes - len(self._buffer)
            width = min(capacity, len(view) - offset)
            self._buffer.extend(view[offset : offset + width])
            offset += width
            self.statistics.peak_buffer_bytes = max(
                self.statistics.peak_buffer_bytes, len(self._buffer)
            )
            decoded.extend(self._drain_buffer())
        return decoded

    def _drain_buffer(self) -> list[RawFrame]:
        decoded: list[RawFrame] = []
        while self._align_to_header() and len(self._buffer) >= FRAME_LENGTH:
            candidate = bytes(self._buffer[:FRAME_LENGTH])
            failure = self._validation_failure(candidate)
            if failure is None:
                del self._buffer[:FRAME_LENGTH]
                decoded.append(self._decode(candidate))
                continue
            self.statistics.invalid_frames += 1
            counter_name = f"{failure}_failures"
            if hasattr(self.statistics, counter_name):
                setattr(
                    self.statistics,
                    counter_name,
                    getattr(self.statistics, counter_name) + 1,
                )
            self._discard_to_next_header()
        return decoded

    def _validation_failure(self, frame: bytes) -> str | None:
        wire_length = int.from_bytes(
            frame[LENGTH_OFFSET:FUNCTION_OFFSET], self.profile.length_byte_order
        )
        if wire_length != FRAME_LENGTH:
            return "length"
        if frame[FUNCTION_OFFSET] != FUNCTION_CODE:
            return "function"
        if frame[TAIL_OFFSET] != TAIL:
            return "tail"
        expected = (-sum(frame[self.profile.checksum_start : self.profile.checksum_end])) & 0xFF
        if frame[CHECKSUM_OFFSET] != expected:
            return "checksum"
        return None

    def _align_to_header(self) -> bool:
        index = self._buffer.find(HEADER)
        if index == 0:
            return True
        if index > 0:
            self._discard_prefix(index)
            return True
        keep = 1 if self._buffer.endswith(HEADER[:1]) else 0
        discard = len(self._buffer) - keep
        if discard:
            self._discard_prefix(discard)
        return False

    def _discard_to_next_header(self) -> None:
        index = self._buffer.find(HEADER, 1)
        if index > 0:
            self._discard_prefix(index)
            return
        keep = 1 if self._buffer.endswith(HEADER[:1]) else 0
        self._discard_prefix(len(self._buffer) - keep)

    def _discard_prefix(self, count: int) -> None:
        if count <= 0:
            return
        del self._buffer[:count]
        self.statistics.resynchronizations += 1
        self.statistics.discarded_bytes += count

    def _decode(self, frame: bytes) -> RawFrame:
        values = np.frombuffer(
            frame[PAYLOAD_OFFSET:CHECKSUM_OFFSET], dtype="<u2"
        ).astype(np.uint16, copy=True)
        values &= 0x0FFF
        values = values.reshape(48, 64)
        values.setflags(write=False)
        quality_flags: set[str] = set()
        if self.profile.evidence is not ProfileEvidence.CAPTURE_VERIFIED:
            quality_flags.add("PROTOCOL_PROFILE_UNVERIFIED")
        host_monotonic_ns = self._monotonic_ns()
        decoded = RawFrame(
            values=values,
            host_monotonic_ns=host_monotonic_ns,
            host_wall_time_ns=self._wall_time_ns(),
            source_index=self._next_source_index,
            device_frame_seq=None,
            device_timestamp_ns=None,
            quality_flags=frozenset(quality_flags),
        )
        self._next_source_index += 1
        self.statistics.record_valid_frame(host_monotonic_ns)
        return decoded
