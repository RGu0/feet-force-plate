from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import replace
from enum import StrEnum
import math
import time
import uuid
from typing import Any, Protocol

from .models import DeviceValidationRun, ValidationOutcome, ValidationReason
from .service import CollectionPhase, CollectionProgress, ValidationRequest


class DeviceNotFound(ConnectionError):
    """No supported device was available during startup discovery."""


class DeviceIdentityMismatch(DeviceNotFound):
    """The connected physical device is not the License-bound device."""


class DeviceBusy(ConnectionError):
    """A supported device exists but another process owns it."""


@dataclass(frozen=True, slots=True)
class ValidationConnection:
    device_ref: str
    transport: Any
    parser: Any
    hardware_identity: str | None = None


class ValidationConnector(Protocol):
    def connect(self) -> ValidationConnection: ...


class StartupValidationState(StrEnum):
    BOOTSTRAPPING = "BOOTSTRAPPING"
    CONNECTING = "CONNECTING"
    WAITING_FOR_EMPTY = "WAITING_FOR_EMPTY"
    COLLECTING_BASELINE = "COLLECTING_BASELINE"
    VALIDATING = "VALIDATING"
    PASSED = "PASSED"
    DEVICE_NOT_FOUND = "DEVICE_NOT_FOUND"
    DEVICE_BUSY = "DEVICE_BUSY"
    LOAD_NOT_EMPTY = "LOAD_NOT_EMPTY"
    STREAM_INTERRUPTED = "STREAM_INTERRUPTED"
    SIGNAL_INVALID = "SIGNAL_INVALID"
    SERVICE_REQUIRED = "SERVICE_REQUIRED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class StartupProgressMode(StrEnum):
    HIDDEN = "HIDDEN"
    INDETERMINATE = "INDETERMINATE"
    DETERMINATE = "DETERMINATE"
    COMPLETE = "COMPLETE"


@dataclass(frozen=True, slots=True)
class StartupPresentation:
    state: StartupValidationState
    title: str
    message: str
    progress_mode: StartupProgressMode
    progress_fraction: float | None = None
    countdown_seconds: int | None = None
    primary_action: str | None = None
    error_code: str | None = None
    can_exit: bool = True


_STATE_COPY: dict[StartupValidationState, tuple[str, str]] = {
    StartupValidationState.BOOTSTRAPPING: (
        "正在初始化",
        "正在检查本地组件，请稍候。",
    ),
    StartupValidationState.CONNECTING: (
        "正在连接压力设备",
        "请保持设备已通电并连接到当前电脑。",
    ),
    StartupValidationState.WAITING_FOR_EMPTY: (
        "请保持设备表面空载",
        "设备表面请勿站人、请勿放置物品。",
    ),
    StartupValidationState.COLLECTING_BASELINE: (
        "正在采集基线数据",
        "设备表面请勿站人、请勿放置物品。",
    ),
    StartupValidationState.VALIDATING: (
        "正在分析设备状态",
        "正在确认设备是否可以开始检测。",
    ),
    StartupValidationState.PASSED: (
        "设备已准备就绪",
        "启动检查已通过，正在进入工作台。",
    ),
    StartupValidationState.DEVICE_NOT_FOUND: (
        "未检测到压力设备",
        "请检查设备电源和连接线，然后重新连接。",
    ),
    StartupValidationState.DEVICE_BUSY: (
        "压力设备暂时无法使用",
        "请关闭其他可能正在使用压力设备的程序，然后重试。",
    ),
    StartupValidationState.LOAD_NOT_EMPTY: (
        "设备表面需要清空",
        "请移开设备表面的人和物品，然后重新开始检查。",
    ),
    StartupValidationState.STREAM_INTERRUPTED: (
        "设备数据已中断",
        "请检查连接是否稳固，然后重新校验。",
    ),
    StartupValidationState.SIGNAL_INVALID: (
        "设备状态需要重新确认",
        "请保持设备表面空载，然后重新校验。",
    ),
    StartupValidationState.SERVICE_REQUIRED: (
        "设备需要技术支持",
        "请记录诊断编号并联系技术支持。您也可以在确认设备表面空载后再次校验。",
    ),
    StartupValidationState.INTERNAL_ERROR: (
        "暂时无法完成启动检查",
        "请重新启动软件；如仍无法完成，请记录诊断编号并联系支持。",
    ),
}

_FAILURE_ACTIONS = {
    StartupValidationState.DEVICE_NOT_FOUND: "重新连接",
    StartupValidationState.DEVICE_BUSY: "关闭占用程序后重试",
    StartupValidationState.LOAD_NOT_EMPTY: "清空设备",
    StartupValidationState.STREAM_INTERRUPTED: "重新校验",
    StartupValidationState.SIGNAL_INVALID: "重新校验",
    StartupValidationState.SERVICE_REQUIRED: "再次校验",
    StartupValidationState.INTERNAL_ERROR: "重试启动检查",
}

_FAILURE_CODES = {
    StartupValidationState.DEVICE_NOT_FOUND: "E-DEV-101",
    StartupValidationState.DEVICE_BUSY: "E-DEV-102",
    StartupValidationState.LOAD_NOT_EMPTY: "E-DEV-103",
    StartupValidationState.STREAM_INTERRUPTED: "E-ACQ-104",
    StartupValidationState.SIGNAL_INVALID: "E-DEV-109",
    StartupValidationState.SERVICE_REQUIRED: "E-DEV-109",
    StartupValidationState.INTERNAL_ERROR: "E-INI-006",
}


def presentation_for(
    state: StartupValidationState,
    *,
    progress: CollectionProgress | None = None,
    error_code: str | None = None,
) -> StartupPresentation:
    title, message = _STATE_COPY[state]
    if state is StartupValidationState.COLLECTING_BASELINE:
        if progress is None:
            raise ValueError("collection progress is required")
        remaining_ns = max(0, progress.duration_ns - progress.elapsed_ns)
        return StartupPresentation(
            state=state,
            title=title,
            message=message,
            progress_mode=StartupProgressMode.DETERMINATE,
            progress_fraction=progress.fraction,
            countdown_seconds=math.ceil(remaining_ns / 1_000_000_000),
        )
    if state is StartupValidationState.PASSED:
        return StartupPresentation(
            state=state,
            title=title,
            message=message,
            progress_mode=StartupProgressMode.COMPLETE,
            progress_fraction=1.0,
            countdown_seconds=0,
        )
    if state in _FAILURE_ACTIONS:
        return StartupPresentation(
            state=state,
            title=title,
            message=message,
            progress_mode=StartupProgressMode.HIDDEN,
            primary_action=_FAILURE_ACTIONS[state],
            error_code=error_code or _FAILURE_CODES[state],
        )
    return StartupPresentation(
        state=state,
        title=title,
        message=message,
        progress_mode=StartupProgressMode.INDETERMINATE,
    )


_SIGNAL_REASONS = {
    ValidationReason.SIGNAL_INVALID,
    ValidationReason.FIXED_VALUE_AREA,
    ValidationReason.SATURATION,
    ValidationReason.NO_VARIATION,
    ValidationReason.LOCAL_ANOMALY,
    ValidationReason.NOISE,
    ValidationReason.DRIFT,
}

_STREAM_REASONS = {
    ValidationReason.STREAM_INTERRUPTED,
    ValidationReason.NO_DATA,
    ValidationReason.WINDOW_INCOMPLETE,
    ValidationReason.RATE_OUT_OF_RANGE,
    ValidationReason.GAP_TOO_LARGE,
}


class StartupValidationCoordinator:
    """Mandatory launch gate; a fresh connector is used for every attempt."""

    def __init__(
        self,
        *,
        connector: ValidationConnector,
        service_factory: Callable[[ValidationConnection], Any],
        terminal_id: str,
        app_version: str,
        on_presentation: Callable[[StartupPresentation], None] | None = None,
        run_policy: Callable[[DeviceValidationRun], DeviceValidationRun] | None = None,
        run_sink: Callable[[DeviceValidationRun], None] | None = None,
        wall_time_ns: Callable[[], int] = time.time_ns,
        id_factory: Callable[[], str] = lambda: str(uuid.uuid4()),
    ) -> None:
        self._connector = connector
        self._service_factory = service_factory
        self._terminal_id = terminal_id
        self._app_version = app_version
        self._on_presentation = on_presentation or (lambda _model: None)
        self._run_policy = run_policy or (lambda run: run)
        self._run_sink = run_sink or (lambda _run: None)
        self._wall_time_ns = wall_time_ns
        self._id_factory = id_factory
        self._presentation = presentation_for(StartupValidationState.BOOTSTRAPPING)
        self._last_run: DeviceValidationRun | None = None

    @property
    def presentation(self) -> StartupPresentation:
        return self._presentation

    @property
    def can_enter_workbench(self) -> bool:
        return self._presentation.state is StartupValidationState.PASSED

    def run(self) -> DeviceValidationRun:
        previous = self._last_run
        attempt = 1 if previous is None else previous.attempt_number + 1
        self._emit(StartupValidationState.BOOTSTRAPPING)
        self._emit(StartupValidationState.CONNECTING)
        try:
            connection = self._connector.connect()
        except DeviceNotFound:
            return self._connection_failure(
                ValidationReason.DEVICE_NOT_FOUND,
                StartupValidationState.DEVICE_NOT_FOUND,
                previous,
                attempt,
            )
        except DeviceBusy:
            return self._connection_failure(
                ValidationReason.DEVICE_BUSY,
                StartupValidationState.DEVICE_BUSY,
                previous,
                attempt,
            )
        except Exception:
            return self._connection_failure(
                ValidationReason.INTERNAL_ERROR,
                StartupValidationState.INTERNAL_ERROR,
                previous,
                attempt,
            )

        service = self._service_factory(connection)
        request = ValidationRequest(
            terminal_id=self._terminal_id,
            device_ref=connection.device_ref,
            app_version=self._app_version,
            previous_validation_run_id=(
                None if previous is None else previous.validation_run_id
            ),
            attempt_number=attempt,
        )
        try:
            run = service.run(request, on_progress=self._on_collection_progress)
        except Exception:
            return self._connection_failure(
                ValidationReason.INTERNAL_ERROR,
                StartupValidationState.INTERNAL_ERROR,
                previous,
                attempt,
                device_ref=connection.device_ref,
            )
        run = self._run_policy(run)
        run = self._record_or_make_recoverable(run)
        if run.reason is ValidationReason.INTERNAL_ERROR:
            self._emit(StartupValidationState.INTERNAL_ERROR, error_code=run.error_code)
            return run
        if run.outcome is ValidationOutcome.PASS:
            self._emit(StartupValidationState.PASSED)
            return run
        state = (
            StartupValidationState.SERVICE_REQUIRED
            if run.outcome is ValidationOutcome.SERVICE_REQUIRED
            else self._failure_state(run.reason)
        )
        self._emit(state, error_code=run.error_code)
        return run

    def retry(self) -> DeviceValidationRun:
        if self._last_run is None:
            raise RuntimeError("validation has not run")
        return self.run()

    def _on_collection_progress(self, progress: CollectionProgress) -> None:
        state = {
            CollectionPhase.WAITING_FOR_EMPTY: StartupValidationState.WAITING_FOR_EMPTY,
            CollectionPhase.COLLECTING_BASELINE: StartupValidationState.COLLECTING_BASELINE,
            CollectionPhase.VALIDATING: StartupValidationState.VALIDATING,
        }[progress.phase]
        self._emit(state, progress=progress)

    def _emit(
        self,
        state: StartupValidationState,
        *,
        progress: CollectionProgress | None = None,
        error_code: str | None = None,
    ) -> None:
        self._presentation = presentation_for(
            state,
            progress=progress,
            error_code=error_code,
        )
        self._on_presentation(self._presentation)

    def _connection_failure(
        self,
        reason: ValidationReason,
        state: StartupValidationState,
        previous: DeviceValidationRun | None,
        attempt: int,
        *,
        device_ref: str = "unavailable-device",
    ) -> DeviceValidationRun:
        now = self._wall_time_ns()
        run = DeviceValidationRun(
            validation_run_id=self._id_factory(),
            previous_validation_run_id=(
                None if previous is None else previous.validation_run_id
            ),
            terminal_id=self._terminal_id,
            device_ref=device_ref,
            attempt_number=attempt,
            app_version=self._app_version,
            protocol_version="unavailable",
            data_mode_version="48x64-uint8-column-major/1",
            rules_version="startup-baseline/1",
            threshold_version="startup-baseline-thresholds/1",
            started_at_wall_ns=now,
            completed_at_wall_ns=now,
            outcome=ValidationOutcome.RETRYABLE_FAIL,
            reason=reason,
            error_code=_FAILURE_CODES[state],
            diagnostic_id=self._id_factory(),
            statistics=None,
            transition_names=(
                StartupValidationState.BOOTSTRAPPING.value,
                StartupValidationState.CONNECTING.value,
                state.value,
            ),
        )
        resolved_run = self._run_policy(run)
        resolved_run = self._record_or_make_recoverable(resolved_run)
        resolved_state = (
            StartupValidationState.SERVICE_REQUIRED
            if resolved_run.outcome is ValidationOutcome.SERVICE_REQUIRED
            else (
                StartupValidationState.INTERNAL_ERROR
                if resolved_run.reason is ValidationReason.INTERNAL_ERROR
                else state
            )
        )
        self._emit(resolved_state, error_code=resolved_run.error_code)
        return resolved_run

    def _record_or_make_recoverable(
        self,
        run: DeviceValidationRun,
    ) -> DeviceValidationRun:
        """Keep an attempt available for retry even when durable audit storage fails."""

        # The preceding attempt is a linkage/audit value, not proof that it was
        # durably persisted.  Store it before calling the fallible sink so a
        # retry always creates a fresh connection and run context.
        self._last_run = run
        try:
            self._run_sink(run)
        except Exception:
            recoverable = replace(
                run,
                outcome=ValidationOutcome.RETRYABLE_FAIL,
                reason=ValidationReason.INTERNAL_ERROR,
                error_code=_FAILURE_CODES[StartupValidationState.INTERNAL_ERROR],
                diagnostic_id=self._id_factory(),
            )
            self._last_run = recoverable
            return recoverable
        return run

    @staticmethod
    def _failure_state(reason: ValidationReason | None) -> StartupValidationState:
        if reason is ValidationReason.LOAD_NOT_EMPTY:
            return StartupValidationState.LOAD_NOT_EMPTY
        if reason in _STREAM_REASONS:
            return StartupValidationState.STREAM_INTERRUPTED
        if reason in _SIGNAL_REASONS:
            return StartupValidationState.SIGNAL_INVALID
        return StartupValidationState.INTERNAL_ERROR
