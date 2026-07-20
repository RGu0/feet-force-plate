"""Bounded raw-frame pipeline and version contracts for DO-P4864 sessions."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from queue import Empty, Full
import string
import threading
import time
from typing import Callable

import numpy as np

from .acquisition import LatestFrameMailbox, QueuedFrame
from .protocol import RawFrame


RAW_COUNT_UNIT = "raw_count"


class UnverifiedCalibrationError(ValueError):
    """Physical units were requested without traceable calibration evidence."""


@dataclass(frozen=True, slots=True)
class BufferMetrics:
    accepted_frames: int
    consumed_frames: int
    rejected_frames: int
    silently_dropped_frames: int
    producer_waits: int
    peak_depth: int


class PreallocatedFrameBuffer:
    """Fixed-slot blocking FIFO for the storage path.

    A full buffer either blocks for capacity or raises ``queue.Full`` when the
    caller's explicit timeout expires. It never evicts an accepted frame.
    """

    def __init__(self, *, capacity: int) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        self._slots: list[QueuedFrame | None] = [None] * capacity
        self._read_index = 0
        self._write_index = 0
        self._count = 0
        self._accepted_frames = 0
        self._consumed_frames = 0
        self._rejected_frames = 0
        self._producer_waits = 0
        self._peak_depth = 0
        self._condition = threading.Condition()

    @property
    def allocated_slots(self) -> int:
        return len(self._slots)

    @property
    def size(self) -> int:
        with self._condition:
            return self._count

    @property
    def metrics(self) -> BufferMetrics:
        with self._condition:
            return BufferMetrics(
                accepted_frames=self._accepted_frames,
                consumed_frames=self._consumed_frames,
                rejected_frames=self._rejected_frames,
                silently_dropped_frames=0,
                producer_waits=self._producer_waits,
                peak_depth=self._peak_depth,
            )

    def append(
        self, session_id: str, frame: RawFrame, *, timeout: float | None = None
    ) -> None:
        if not session_id:
            raise ValueError("session_id is required")
        if timeout is not None and timeout < 0:
            raise ValueError("timeout cannot be negative")
        deadline = None if timeout is None else time.monotonic() + timeout
        counted_wait = False
        with self._condition:
            while self._count == len(self._slots):
                if not counted_wait:
                    self._producer_waits += 1
                    counted_wait = True
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    self._rejected_frames += 1
                    raise Full
                self._condition.wait(remaining)
            self._slots[self._write_index] = QueuedFrame(session_id, frame)
            self._write_index = (self._write_index + 1) % len(self._slots)
            self._count += 1
            self._accepted_frames += 1
            self._peak_depth = max(self._peak_depth, self._count)
            self._condition.notify_all()

    def get(self, *, timeout: float | None = None) -> QueuedFrame:
        if timeout is not None and timeout < 0:
            raise ValueError("timeout cannot be negative")
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._condition:
            while self._count == 0:
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    raise Empty
                self._condition.wait(remaining)
            item = self._slots[self._read_index]
            if item is None:
                raise AssertionError("occupied preallocated slot was unexpectedly empty")
            self._slots[self._read_index] = None
            self._read_index = (self._read_index + 1) % len(self._slots)
            self._count -= 1
            self._consumed_frames += 1
            self._condition.notify_all()
            return item

    def get_nowait(self) -> QueuedFrame:
        return self.get(timeout=0.0)


@dataclass(frozen=True, slots=True)
class ProcessingProfile:
    algorithm_version: str
    filter_version: str
    bad_point_version: str
    interpolation_version: str
    calibration_version: str | None
    output_unit: str
    calibration_fixture_sha256: str | None = None
    filter_parameters: tuple[tuple[str, float], ...] = ()
    bad_points: tuple[tuple[int, int], ...] = ()
    interpolation_parameters: tuple[tuple[str, float], ...] = ()

    def __post_init__(self) -> None:
        required = (
            self.algorithm_version,
            self.filter_version,
            self.bad_point_version,
            self.interpolation_version,
            self.output_unit,
        )
        if any(not value for value in required):
            raise ValueError("processing profile versions and output_unit are required")
        for row, column in self.bad_points:
            if not 0 <= row < 48 or not 0 <= column < 64:
                raise ValueError("bad point coordinates must fit the 48x64 matrix")
        for name, _ in (*self.filter_parameters, *self.interpolation_parameters):
            if not name:
                raise ValueError("processing parameter names cannot be empty")
        if self.output_unit != RAW_COUNT_UNIT:
            digest = (self.calibration_fixture_sha256 or "").lower()
            if self.calibration_version is None or len(digest) != 64 or any(
                char not in string.hexdigits for char in digest
            ):
                raise UnverifiedCalibrationError(
                    "physical output requires a calibration version and fixture SHA-256"
                )

    @classmethod
    def raw_counts_only(
        cls,
        *,
        algorithm_version: str,
        filter_version: str,
        bad_point_version: str,
        interpolation_version: str,
        filter_parameters: tuple[tuple[str, float], ...] = (),
        bad_points: tuple[tuple[int, int], ...] = (),
        interpolation_parameters: tuple[tuple[str, float], ...] = (),
    ) -> ProcessingProfile:
        return cls(
            algorithm_version=algorithm_version,
            filter_version=filter_version,
            bad_point_version=bad_point_version,
            interpolation_version=interpolation_version,
            calibration_version=None,
            output_unit=RAW_COUNT_UNIT,
            filter_parameters=filter_parameters,
            bad_points=bad_points,
            interpolation_parameters=interpolation_parameters,
        )

    @property
    def identity_sha256(self) -> str:
        encoded = json.dumps(asdict(self), sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class DisplayFrame:
    raw_frame: RawFrame
    values: np.ndarray
    unit: str
    processing_profile: ProcessingProfile


class VersionedDisplayProcessor:
    """Creates a separate display projection while preserving the raw frame."""

    def __init__(
        self,
        profile: ProcessingProfile,
        *,
        physical_transform: Callable[[np.ndarray], np.ndarray] | None = None,
    ) -> None:
        if profile.output_unit != RAW_COUNT_UNIT and physical_transform is None:
            raise UnverifiedCalibrationError(
                "physical output requires an explicit calibrated transform"
            )
        self._profile = profile
        self._physical_transform = physical_transform

    def project(self, raw_frame: RawFrame) -> DisplayFrame:
        if raw_frame.values.shape != (48, 64) or raw_frame.values.dtype != np.uint16:
            raise ValueError("raw DO-P4864 frames must be 48x64 uint16")
        if self._profile.output_unit == RAW_COUNT_UNIT:
            values = raw_frame.values.copy()
        else:
            if self._physical_transform is None:
                raise AssertionError("validated physical transform is missing")
            values = np.asarray(self._physical_transform(raw_frame.values)).copy()
            if values.shape != (48, 64):
                raise ValueError("calibrated display values must retain shape (48, 64)")
        values.setflags(write=False)
        return DisplayFrame(
            raw_frame=raw_frame,
            values=values,
            unit=self._profile.output_unit,
            processing_profile=self._profile,
        )


@dataclass(frozen=True, slots=True)
class SessionVersionManifest:
    data_schema_version: str
    device_model: str
    protocol_version: str
    calibration_version: str
    algorithm_version: str
    filter_version: str
    bad_point_version: str
    interpolation_version: str
    test_protocol_version: str
    acquisition_mode: str

    def __post_init__(self) -> None:
        if any(not value for value in asdict(self).values()):
            raise ValueError("every session version field must be explicit")

    def to_json_bytes(self) -> bytes:
        return json.dumps(
            asdict(self), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")

    @classmethod
    def from_json_bytes(cls, encoded: bytes) -> SessionVersionManifest:
        payload = json.loads(encoded.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("session version manifest must be a JSON object")
        return cls(**payload)


@dataclass(frozen=True, slots=True)
class DisplayTick:
    frame: RawFrame
    is_new_source: bool


class DisplayCadence:
    """UI polling clock that is explicitly separate from device sample timing."""

    def __init__(
        self,
        mailbox: LatestFrameMailbox,
        *,
        input_nominal_hz: float,
        refresh_hz: float,
        start_monotonic_ns: int,
    ) -> None:
        if input_nominal_hz <= 0 or refresh_hz <= 0:
            raise ValueError("input_nominal_hz and refresh_hz must be positive")
        self._mailbox = mailbox
        self.input_nominal_hz = float(input_nominal_hz)
        self.refresh_hz = float(refresh_hz)
        self._period_ns = round(1_000_000_000 / refresh_hz)
        self._next_refresh_ns = start_monotonic_ns
        self._last_source_index: int | None = None

    def poll(self, *, now_monotonic_ns: int) -> DisplayTick | None:
        if now_monotonic_ns < self._next_refresh_ns:
            return None
        periods = max(
            1,
            (now_monotonic_ns - self._next_refresh_ns) // self._period_ns + 1,
        )
        self._next_refresh_ns += periods * self._period_ns
        frame = self._mailbox.read()
        if frame is None:
            return None
        is_new_source = frame.source_index != self._last_source_index
        self._last_source_index = frame.source_index
        return DisplayTick(frame=frame, is_new_source=is_new_source)
