from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
import time
import uuid

from client.device.protocol import FRAME_LENGTH, DaoOneP4864Parser, RawFrame
from client.device.transport import ByteTransport, TransportDisconnected

from .models import (
    DeviceValidationRun,
    ValidationOutcome,
    ValidationReason,
    ValidationStatistics,
)
from .rules import ValidationThresholds, evaluate_baseline, is_obviously_loaded


class CollectionPhase(StrEnum):
    WAITING_FOR_EMPTY = "WAITING_FOR_EMPTY"
    COLLECTING_BASELINE = "COLLECTING_BASELINE"
    VALIDATING = "VALIDATING"


@dataclass(frozen=True, slots=True)
class CollectionProgress:
    phase: CollectionPhase
    elapsed_ns: int
    duration_ns: int

    @property
    def fraction(self) -> float:
        if self.duration_ns <= 0:
            return 0.0
        return min(1.0, max(0.0, self.elapsed_ns / self.duration_ns))


@dataclass(frozen=True, slots=True)
class ValidationRequest:
    terminal_id: str
    device_ref: str
    app_version: str
    previous_validation_run_id: str | None = None
    attempt_number: int = 1

    def __post_init__(self) -> None:
        if not self.terminal_id or not self.device_ref or not self.app_version:
            raise ValueError("terminal, device, and app references are required")
        if self.attempt_number <= 0:
            raise ValueError("attempt_number must be positive")


_ERROR_CODES = {
    ValidationReason.LOAD_NOT_EMPTY: "E-DEV-103",
    ValidationReason.STREAM_INTERRUPTED: "E-ACQ-104",
    ValidationReason.NO_DATA: "E-ACQ-105",
    ValidationReason.WINDOW_INCOMPLETE: "E-ACQ-106",
    ValidationReason.RATE_OUT_OF_RANGE: "E-ACQ-107",
    ValidationReason.GAP_TOO_LARGE: "E-ACQ-108",
    ValidationReason.SIGNAL_INVALID: "E-DEV-109",
    ValidationReason.FIXED_VALUE_AREA: "E-DEV-109",
    ValidationReason.SATURATION: "E-DEV-109",
    ValidationReason.NO_VARIATION: "E-DEV-109",
    ValidationReason.LOCAL_ANOMALY: "E-DEV-109",
    ValidationReason.NOISE: "E-DEV-109",
    ValidationReason.DRIFT: "E-DEV-109",
    ValidationReason.INTERNAL_ERROR: "E-INI-006",
}


class DeviceValidationService:
    """Collect a fresh baseline through the production byte/parser boundary."""

    def __init__(
        self,
        *,
        transport: ByteTransport,
        parser: DaoOneP4864Parser,
        thresholds: ValidationThresholds | None = None,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
        wall_time_ns: Callable[[], int] = time.time_ns,
        id_factory: Callable[[], str] = lambda: str(uuid.uuid4()),
        diagnostic_id_factory: Callable[[], str] = lambda: str(uuid.uuid4()),
        read_size: int = FRAME_LENGTH,
        no_data_timeout_ns: int = 2_000_000_000,
    ) -> None:
        if read_size <= 0:
            raise ValueError("read_size must be positive")
        if no_data_timeout_ns <= 0:
            raise ValueError("no_data_timeout_ns must be positive")
        self._transport = transport
        self._parser = parser
        self._thresholds = thresholds or ValidationThresholds()
        self._monotonic_ns = monotonic_ns
        self._wall_time_ns = wall_time_ns
        self._id_factory = id_factory
        self._diagnostic_id_factory = diagnostic_id_factory
        self._read_size = read_size
        self._no_data_timeout_ns = no_data_timeout_ns

    def run(
        self,
        request: ValidationRequest,
        *,
        on_progress: Callable[[CollectionProgress], None] | None = None,
    ) -> DeviceValidationRun:
        emit = on_progress or (lambda _progress: None)
        started_at_wall_ns = self._wall_time_ns()
        run_started_monotonic_ns = self._monotonic_ns()
        validation_run_id = self._id_factory()
        diagnostic_id = self._diagnostic_id_factory()
        frames: list[RawFrame] = []
        baseline_start_ns: int | None = None
        last_frame_ns: int | None = None
        start_invalid = self._parser.statistics.invalid_frames
        start_resynchronizations = self._parser.statistics.resynchronizations
        transitions = [CollectionPhase.WAITING_FOR_EMPTY.value]
        emit(
            CollectionProgress(
                CollectionPhase.WAITING_FOR_EMPTY,
                0,
                self._thresholds.window_duration_ns,
            )
        )
        try:
            while True:
                try:
                    chunk = self._transport.read(self._read_size)
                except TransportDisconnected:
                    return self._failed_run(
                        request=request,
                        validation_run_id=validation_run_id,
                        diagnostic_id=diagnostic_id,
                        started_at_wall_ns=started_at_wall_ns,
                        reason=ValidationReason.STREAM_INTERRUPTED,
                        frames=tuple(frames),
                        start_invalid=start_invalid,
                        start_resynchronizations=start_resynchronizations,
                        transitions=tuple(transitions),
                    )
                if not chunk:
                    now = self._monotonic_ns()
                    reference = (
                        run_started_monotonic_ns
                        if last_frame_ns is None
                        else last_frame_ns
                    )
                    timeout_ns = (
                        self._no_data_timeout_ns
                        if last_frame_ns is None
                        else self._thresholds.maximum_gap_ns
                    )
                    if now - reference > timeout_ns:
                        reason = (
                            ValidationReason.NO_DATA
                            if last_frame_ns is None
                            else ValidationReason.STREAM_INTERRUPTED
                        )
                        return self._failed_run(
                            request=request,
                            validation_run_id=validation_run_id,
                            diagnostic_id=diagnostic_id,
                            started_at_wall_ns=started_at_wall_ns,
                            reason=reason,
                            frames=tuple(frames),
                            start_invalid=start_invalid,
                            start_resynchronizations=start_resynchronizations,
                            transitions=tuple(transitions),
                        )
                    continue

                for frame in self._parser.feed(chunk):
                    if last_frame_ns is not None and (
                        frame.host_monotonic_ns - last_frame_ns
                        > self._thresholds.maximum_gap_ns
                    ):
                        return self._failed_run(
                            request=request,
                            validation_run_id=validation_run_id,
                            diagnostic_id=diagnostic_id,
                            started_at_wall_ns=started_at_wall_ns,
                            reason=ValidationReason.STREAM_INTERRUPTED,
                            frames=tuple(frames),
                            start_invalid=start_invalid,
                            start_resynchronizations=start_resynchronizations,
                            transitions=tuple(transitions),
                        )
                    last_frame_ns = frame.host_monotonic_ns
                    if is_obviously_loaded(frame, self._thresholds):
                        frames.append(frame)
                        return self._failed_run(
                            request=request,
                            validation_run_id=validation_run_id,
                            diagnostic_id=diagnostic_id,
                            started_at_wall_ns=started_at_wall_ns,
                            reason=ValidationReason.LOAD_NOT_EMPTY,
                            frames=tuple(frames),
                            start_invalid=start_invalid,
                            start_resynchronizations=start_resynchronizations,
                            transitions=tuple(transitions),
                        )
                    if baseline_start_ns is None:
                        baseline_start_ns = frame.host_monotonic_ns
                        transitions.append(CollectionPhase.COLLECTING_BASELINE.value)
                    frames.append(frame)
                    elapsed_ns = frame.host_monotonic_ns - baseline_start_ns
                    emit(
                        CollectionProgress(
                            CollectionPhase.COLLECTING_BASELINE,
                            elapsed_ns,
                            self._thresholds.window_duration_ns,
                        )
                    )
                    if elapsed_ns < self._thresholds.window_duration_ns:
                        continue
                    transitions.append(CollectionPhase.VALIDATING.value)
                    emit(
                        CollectionProgress(
                            CollectionPhase.VALIDATING,
                            self._thresholds.window_duration_ns,
                            self._thresholds.window_duration_ns,
                        )
                    )
                    frame_tuple = tuple(frames)
                    statistics = self._statistics(
                        frame_tuple,
                        start_invalid=start_invalid,
                        start_resynchronizations=start_resynchronizations,
                    )
                    evaluation = evaluate_baseline(
                        frame_tuple,
                        statistics,
                        self._thresholds,
                    )
                    reason = evaluation.reasons[0] if evaluation.reasons else None
                    return DeviceValidationRun(
                        validation_run_id=validation_run_id,
                        previous_validation_run_id=request.previous_validation_run_id,
                        terminal_id=request.terminal_id,
                        device_ref=request.device_ref,
                        attempt_number=request.attempt_number,
                        app_version=request.app_version,
                        protocol_version=self._parser.profile.version,
                        data_mode_version="48x64-uint8-column-major/1",
                        rules_version=self._thresholds.rules_version,
                        threshold_version=self._thresholds.version,
                        started_at_wall_ns=started_at_wall_ns,
                        completed_at_wall_ns=self._wall_time_ns(),
                        outcome=evaluation.outcome,
                        reason=reason,
                        error_code=None if reason is None else _ERROR_CODES.get(reason, "E-DEV-109"),
                        diagnostic_id=diagnostic_id,
                        statistics=statistics,
                        transition_names=tuple(transitions),
                        partial_window_discarded=reason is not None,
                    )
        finally:
            self._transport.close()

    def _failed_run(
        self,
        *,
        request: ValidationRequest,
        validation_run_id: str,
        diagnostic_id: str,
        started_at_wall_ns: int,
        reason: ValidationReason,
        frames: tuple[RawFrame, ...],
        start_invalid: int,
        start_resynchronizations: int,
        transitions: tuple[str, ...],
    ) -> DeviceValidationRun:
        statistics = (
            self._statistics(
                frames,
                start_invalid=start_invalid,
                start_resynchronizations=start_resynchronizations,
            )
            if frames
            else None
        )
        return DeviceValidationRun(
            validation_run_id=validation_run_id,
            previous_validation_run_id=request.previous_validation_run_id,
            terminal_id=request.terminal_id,
            device_ref=request.device_ref,
            attempt_number=request.attempt_number,
            app_version=request.app_version,
            protocol_version=self._parser.profile.version,
            data_mode_version="48x64-uint8-column-major/1",
            rules_version=self._thresholds.rules_version,
            threshold_version=self._thresholds.version,
            started_at_wall_ns=started_at_wall_ns,
            completed_at_wall_ns=self._wall_time_ns(),
            outcome=ValidationOutcome.RETRYABLE_FAIL,
            reason=reason,
            error_code=_ERROR_CODES.get(reason, "E-DEV-109"),
            diagnostic_id=diagnostic_id,
            statistics=statistics,
            transition_names=transitions,
            partial_window_discarded=bool(frames),
        )

    def _statistics(
        self,
        frames: tuple[RawFrame, ...],
        *,
        start_invalid: int,
        start_resynchronizations: int,
    ) -> ValidationStatistics:
        return ValidationStatistics.from_frames(
            frames,
            invalid_candidate_count=(
                self._parser.statistics.invalid_frames - start_invalid
            ),
            resynchronization_count=(
                self._parser.statistics.resynchronizations
                - start_resynchronizations
            ),
        )
