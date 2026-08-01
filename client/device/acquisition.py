"""Storage-first acquisition loop shared by physical and simulated transports."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from queue import Queue
import threading
import time
from typing import Callable, Protocol

import numpy as np

from .protocol import (
    FRAME_LENGTH,
    DaoOneP4864Parser,
    ProtocolIntegrityEvent,
    RawFrame,
)
from .transport import ByteTransport, TransportDisconnected


class ConnectionState(StrEnum):
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    READY = "READY"
    ACQUIRING = "ACQUIRING"
    INVALID = "INVALID"
    ERROR = "ERROR"


class AcquisitionOutcome(StrEnum):
    COMPLETED = "COMPLETED"
    INCOMPLETE = "INCOMPLETE"
    INVALID = "INVALID"


def default_maximum_no_valid_signal_ns() -> int:
    """Read the active device's acquisition continuity limit at composition time."""

    from client.hardware_standardization.do_p4864 import DoP4864StandardizationAdapter

    configuration = (
        DoP4864StandardizationAdapter.observed_compact_8bit()
        .specification.startup_validation
    )
    return round(configuration.maximum_no_valid_signal_s * 1_000_000_000)


class IllegalConnectionTransition(RuntimeError):
    """A caller attempted to skip a required device lifecycle transition."""


class ConnectionStateMachine:
    """Small, thread-safe state machine for the owned device connection slice."""

    def __init__(self) -> None:
        self._state = ConnectionState.DISCONNECTED
        self._last_error: str | None = None
        self._lock = threading.Lock()

    @property
    def state(self) -> ConnectionState:
        with self._lock:
            return self._state

    @property
    def last_error(self) -> str | None:
        with self._lock:
            return self._last_error

    def start_connecting(self) -> None:
        self._transition(
            {ConnectionState.DISCONNECTED, ConnectionState.ERROR, ConnectionState.INVALID},
            ConnectionState.CONNECTING,
        )

    def mark_ready(self) -> None:
        self._transition({ConnectionState.CONNECTING}, ConnectionState.READY)
        with self._lock:
            self._last_error = None

    def start_acquiring(self) -> None:
        self._transition({ConnectionState.READY}, ConnectionState.ACQUIRING)

    def finish_acquiring(self) -> None:
        self._transition({ConnectionState.ACQUIRING}, ConnectionState.READY)

    def mark_invalid(self, reason: str) -> None:
        with self._lock:
            if self._state is not ConnectionState.ACQUIRING:
                raise IllegalConnectionTransition(
                    f"cannot enter INVALID from {self._state.value}"
                )
            self._state = ConnectionState.INVALID
            self._last_error = reason

    def mark_error(self, reason: str) -> None:
        with self._lock:
            if self._state not in {
                ConnectionState.CONNECTING,
                ConnectionState.READY,
                ConnectionState.ACQUIRING,
                ConnectionState.INVALID,
            }:
                raise IllegalConnectionTransition(
                    f"cannot enter ERROR from {self._state.value}"
                )
            self._state = ConnectionState.ERROR
            self._last_error = reason

    def mark_disconnected(self) -> None:
        with self._lock:
            self._state = ConnectionState.DISCONNECTED
            self._last_error = None

    def _transition(
        self, allowed: set[ConnectionState], target: ConnectionState
    ) -> None:
        with self._lock:
            if self._state not in allowed:
                raise IllegalConnectionTransition(
                    f"cannot enter {target.value} from {self._state.value}"
                )
            self._state = target


@dataclass(frozen=True, slots=True)
class QueuedFrame:
    session_id: str
    frame: RawFrame


class DurableFrameSink(Protocol):
    """Backpressure-capable handoff to the durable spool writer."""

    def append(
        self, session_id: str, frame: RawFrame, *, timeout: float | None = None
    ) -> None: ...


class InvalidatableFrameSink(DurableFrameSink, Protocol):
    def discard(self, *, reason: str) -> None: ...


class DurableFrameQueue:
    """Bounded FIFO; a full storage path blocks acquisition instead of dropping."""

    def __init__(self, *, capacity: int) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        self._queue: Queue[QueuedFrame] = Queue(maxsize=capacity)

    @property
    def capacity(self) -> int:
        return self._queue.maxsize

    @property
    def size(self) -> int:
        return self._queue.qsize()

    def append(
        self, session_id: str, frame: RawFrame, *, timeout: float | None = None
    ) -> None:
        if not session_id:
            raise ValueError("session_id is required")
        self._queue.put(QueuedFrame(session_id, frame), timeout=timeout)

    def get(self, *, timeout: float | None = None) -> QueuedFrame:
        return self._queue.get(timeout=timeout)

    def get_nowait(self) -> QueuedFrame:
        return self._queue.get_nowait()


class LatestFrameMailbox:
    """Single-slot display/preview handoff; newer frames replace older frames."""

    def __init__(self) -> None:
        self._frame: RawFrame | None = None
        self._publish_count = 0
        self._replacement_count = 0
        self._lock = threading.Lock()

    def publish(self, frame: RawFrame) -> None:
        with self._lock:
            if self._frame is not None:
                self._replacement_count += 1
            self._frame = frame
            self._publish_count += 1

    def read(self) -> RawFrame | None:
        with self._lock:
            return self._frame

    @property
    def publish_count(self) -> int:
        with self._lock:
            return self._publish_count

    @property
    def replacement_count(self) -> int:
        with self._lock:
            return self._replacement_count


@dataclass(frozen=True, slots=True)
class AcquisitionResult:
    session_id: str
    outcome: AcquisitionOutcome
    frames_stored: int
    reason: str | None = None
    integrity_events: tuple["AcquisitionIntegrityEvent", ...] = ()
    reconstructed_frames: tuple[RawFrame, ...] = ()


@dataclass(frozen=True, slots=True)
class AcquisitionIntegrityEvent:
    """Audit of an invalid wire region and any derived-only reconstruction."""

    event_index: int
    failure_kind: str
    invalid_frame_count: int
    discarded_bytes: int
    preceding_source_index: int | None
    following_source_index: int | None
    valid_signal_gap_ns: int | None
    reconstructed_frame_count: int
    resolution: str


class AcquisitionRunner:
    """Blocking reader loop intended to run only inside an AcquisitionWorker."""

    def __init__(
        self,
        *,
        transport: ByteTransport,
        parser: DaoOneP4864Parser,
        durable_sink: DurableFrameSink,
        latest_mailbox: LatestFrameMailbox,
        connection: ConnectionStateMachine,
        read_size: int = FRAME_LENGTH,
        maximum_no_valid_signal_ns: int | None = None,
        storage_append_timeout_s: float | None = None,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
    ) -> None:
        if read_size <= 0:
            raise ValueError("read_size must be positive")
        if maximum_no_valid_signal_ns is None:
            maximum_no_valid_signal_ns = default_maximum_no_valid_signal_ns()
        if maximum_no_valid_signal_ns <= 0:
            raise ValueError("maximum_no_valid_signal_ns must be positive")
        if storage_append_timeout_s is not None and storage_append_timeout_s < 0:
            raise ValueError("storage_append_timeout_s must not be negative when set")
        self._transport = transport
        self._parser = parser
        self._durable_sink = durable_sink
        self._latest_mailbox = latest_mailbox
        self._connection = connection
        self._read_size = read_size
        self._maximum_no_valid_signal_ns = maximum_no_valid_signal_ns
        self._storage_append_timeout_s = storage_append_timeout_s
        self._monotonic_ns = monotonic_ns
        self._used = False

    def _invalidate(
        self,
        session_id: str,
        *,
        frames_stored: int,
        reason: str,
        integrity_events: list[AcquisitionIntegrityEvent],
        reconstructed_frames: list[RawFrame],
    ) -> AcquisitionResult:
        if hasattr(self._durable_sink, "discard"):
            try:
                getattr(self._durable_sink, "discard")(reason=reason)
            except Exception as cleanup_error:
                reason = f"{reason}; temporary cleanup failed: {type(cleanup_error).__name__}"
        self._connection.mark_invalid(reason)
        return AcquisitionResult(
            session_id,
            AcquisitionOutcome.INVALID,
            frames_stored,
            reason,
            tuple(integrity_events),
            tuple(reconstructed_frames),
        )

    def run(
        self,
        *,
        session_id: str,
        target_frames: int | None = None,
        minimum_duration_ns: int | None = None,
    ) -> AcquisitionResult:
        if self._used:
            raise RuntimeError(
                "an acquisition runner is single-use; reconnect must create a new session runner"
            )
        if not session_id:
            raise ValueError("session_id is required")
        if target_frames is not None and target_frames <= 0:
            raise ValueError("target_frames must be positive when set")
        if minimum_duration_ns is not None and minimum_duration_ns <= 0:
            raise ValueError("minimum_duration_ns must be positive when set")
        if target_frames is None and minimum_duration_ns is None:
            raise ValueError("target_frames or minimum_duration_ns is required")
        self._used = True
        self._connection.start_acquiring()
        frames_stored = 0
        previous_frame: RawFrame | None = None
        first_host_monotonic_ns: int | None = None
        last_valid_observed_ns = self._monotonic_ns()
        pending_events: list[ProtocolIntegrityEvent] = []
        integrity_events: list[AcquisitionIntegrityEvent] = []
        reconstructed_frames: list[RawFrame] = []
        try:
            while True:
                chunk = self._transport.read(self._read_size)
                if not chunk:
                    if self._monotonic_ns() - last_valid_observed_ns >= self._maximum_no_valid_signal_ns:
                        return self._invalidate(
                            session_id,
                            frames_stored=frames_stored,
                            reason="no valid decoded signal for five seconds",
                            integrity_events=integrity_events,
                            reconstructed_frames=reconstructed_frames,
                        )
                    continue
                # Serial transports are expected to use bounded reads, but do
                # not let an implementation that returns a late non-empty
                # chunk bypass the same five-second continuity requirement.
                if (
                    self._monotonic_ns() - last_valid_observed_ns
                    >= self._maximum_no_valid_signal_ns
                ):
                    return self._invalidate(
                        session_id,
                        frames_stored=frames_stored,
                        reason="no valid decoded signal for five seconds",
                        integrity_events=integrity_events,
                        reconstructed_frames=reconstructed_frames,
                    )
                decoded = self._parser.feed(chunk)
                pending_events.extend(self._parser.take_integrity_events())
                for frame in decoded:
                    if previous_frame is not None and (
                        frame.host_monotonic_ns - previous_frame.host_monotonic_ns
                        >= self._maximum_no_valid_signal_ns
                    ):
                        return self._invalidate(
                            session_id,
                            frames_stored=frames_stored,
                            reason="no valid decoded signal for five seconds",
                            integrity_events=integrity_events,
                            reconstructed_frames=reconstructed_frames,
                        )
                    resolved, reconstructed = self._resolve_events_before_frame(
                        pending_events, previous_frame, frame
                    )
                    integrity_events.extend(resolved)
                    reconstructed_frames.extend(reconstructed)
                    pending_events = [
                        event
                        for event in pending_events
                        if event.valid_frames_before > frame.source_index
                    ]
                    try:
                        self._durable_sink.append(
                            session_id,
                            frame,
                            timeout=self._storage_append_timeout_s,
                        )
                    except Exception as exc:
                        reason = f"storage handoff failed: {type(exc).__name__}: {exc}"
                        return self._invalidate(
                            session_id,
                            frames_stored=frames_stored,
                            reason=reason,
                            integrity_events=integrity_events,
                            reconstructed_frames=reconstructed_frames,
                        )
                    self._latest_mailbox.publish(frame)
                    previous_frame = frame
                    last_valid_observed_ns = self._monotonic_ns()
                    if first_host_monotonic_ns is None:
                        first_host_monotonic_ns = frame.host_monotonic_ns
                    frames_stored += 1
                    has_target_frame_count = (
                        target_frames is None or frames_stored >= target_frames
                    )
                    has_minimum_duration = (
                        minimum_duration_ns is None
                        or frame.host_monotonic_ns - first_host_monotonic_ns
                        >= minimum_duration_ns
                    )
                    if (
                        has_target_frame_count
                        and has_minimum_duration
                        and not pending_events
                    ):
                        break
                if (
                    (target_frames is None or frames_stored >= target_frames)
                    and (
                        minimum_duration_ns is None
                        or (
                            first_host_monotonic_ns is not None
                            and previous_frame is not None
                            and previous_frame.host_monotonic_ns
                            - first_host_monotonic_ns
                            >= minimum_duration_ns
                        )
                    )
                    and not pending_events
                ):
                    break
        except TransportDisconnected as exc:
            reason = f"transport disconnected: {exc}"
            return self._invalidate(
                session_id,
                frames_stored=frames_stored,
                reason=reason,
                integrity_events=integrity_events,
                reconstructed_frames=reconstructed_frames,
            )
        self._connection.finish_acquiring()
        return AcquisitionResult(
            session_id,
            AcquisitionOutcome.COMPLETED,
            frames_stored,
            integrity_events=tuple(integrity_events),
            reconstructed_frames=tuple(reconstructed_frames),
        )

    @staticmethod
    def _resolve_events_before_frame(
        pending_events: list[ProtocolIntegrityEvent],
        previous_frame: RawFrame | None,
        following_frame: RawFrame,
    ) -> tuple[list[AcquisitionIntegrityEvent], list[RawFrame]]:
        relevant = [
            event
            for event in pending_events
            if event.valid_frames_before <= following_frame.source_index
        ]
        if not relevant:
            return [], []
        if previous_frame is None:
            return (
                [
                    AcquisitionIntegrityEvent(
                        event_index=event.event_index,
                        failure_kind=event.failure_kind,
                        invalid_frame_count=event.invalid_frame_count,
                        discarded_bytes=event.discarded_bytes,
                        preceding_source_index=None,
                        following_source_index=following_frame.source_index,
                        valid_signal_gap_ns=None,
                        reconstructed_frame_count=0,
                        resolution="NO_PRECEDING_VALID_FRAME",
                    )
                    for event in relevant
                ],
                [],
            )
        gap_ns = following_frame.host_monotonic_ns - previous_frame.host_monotonic_ns
        invalid_count = sum(event.invalid_frame_count for event in relevant)
        reconstructed = AcquisitionRunner._interpolate_invalid_frames(
            previous_frame, following_frame, invalid_count, relevant
        )
        audit: list[AcquisitionIntegrityEvent] = []
        remaining = len(reconstructed)
        for event in relevant:
            count = min(event.invalid_frame_count, remaining)
            remaining -= count
            audit.append(
                AcquisitionIntegrityEvent(
                    event_index=event.event_index,
                    failure_kind=event.failure_kind,
                    invalid_frame_count=event.invalid_frame_count,
                    discarded_bytes=event.discarded_bytes,
                    preceding_source_index=previous_frame.source_index,
                    following_source_index=following_frame.source_index,
                    valid_signal_gap_ns=gap_ns,
                    reconstructed_frame_count=count,
                    resolution=(
                        "RECONSTRUCTED_FROM_NEIGHBORS"
                        if count
                        else "RECORDED_NO_MATRIX_RECONSTRUCTION"
                    ),
                )
            )
        return audit, reconstructed

    @staticmethod
    def _interpolate_invalid_frames(
        previous_frame: RawFrame,
        following_frame: RawFrame,
        count: int,
        events: list[ProtocolIntegrityEvent],
    ) -> list[RawFrame]:
        if count <= 0:
            return []
        # A derived frame must retain a strictly ordered host timeline.  On a
        # real serial stream the neighbour gap is many milliseconds, but do
        # not manufacture an ambiguous timestamp for a synthetic or faulty
        # clock with insufficient nanosecond resolution.
        if (
            following_frame.host_monotonic_ns - previous_frame.host_monotonic_ns
            <= count
        ):
            return []
        previous = previous_frame.values.astype(np.float64)
        following = following_frame.values.astype(np.float64)
        event_ids = ",".join(str(event.event_index) for event in events)
        reconstructed: list[RawFrame] = []
        for index in range(1, count + 1):
            fraction = index / (count + 1)
            values = np.rint(previous + fraction * (following - previous)).astype(
                np.uint8
            )
            values.setflags(write=False)
            reconstructed.append(
                RawFrame(
                    values=values,
                    host_monotonic_ns=round(
                        previous_frame.host_monotonic_ns
                        + fraction
                        * (
                            following_frame.host_monotonic_ns
                            - previous_frame.host_monotonic_ns
                        )
                    ),
                    host_wall_time_ns=round(
                        previous_frame.host_wall_time_ns
                        + fraction
                        * (
                            following_frame.host_wall_time_ns
                            - previous_frame.host_wall_time_ns
                        )
                    ),
                    source_index=following_frame.source_index,
                    device_frame_seq=None,
                    device_timestamp_ns=None,
                    quality_flags=frozenset(
                        {
                            "RECONSTRUCTED_FROM_NEIGHBORS",
                            "RAW_FRAME_UNAVAILABLE",
                            f"INTEGRITY_EVENTS_{event_ids}",
                        }
                    ),
                )
            )
        return reconstructed


class AcquisitionWorker:
    """One-shot thread wrapper that keeps serial blocking reads off the caller."""

    def __init__(self, runner: AcquisitionRunner) -> None:
        self._runner = runner
        self._thread: threading.Thread | None = None
        self._result: AcquisitionResult | None = None
        self._error: BaseException | None = None

    def start(self, *, session_id: str, target_frames: int) -> None:
        if self._thread is not None:
            raise RuntimeError("acquisition worker is single-use")

        def target() -> None:
            try:
                self._result = self._runner.run(
                    session_id=session_id, target_frames=target_frames
                )
            except BaseException as exc:
                self._error = exc

        self._thread = threading.Thread(
            target=target,
            name=f"device-acquisition-{session_id}",
            daemon=True,
        )
        self._thread.start()

    def join(self, *, timeout: float | None = None) -> AcquisitionResult:
        if self._thread is None:
            raise RuntimeError("acquisition worker has not started")
        self._thread.join(timeout)
        if self._thread.is_alive():
            raise TimeoutError("acquisition worker did not finish before timeout")
        if self._error is not None:
            raise self._error
        if self._result is None:
            raise RuntimeError("acquisition worker ended without a result")
        return self._result
