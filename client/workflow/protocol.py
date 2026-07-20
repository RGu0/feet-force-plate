from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from math import ceil


class ProtocolParadigm(StrEnum):
    STANDARD_BILATERAL = "STANDARD_BILATERAL"
    EYES_CLOSED = "EYES_CLOSED"
    SINGLE_LEG = "SINGLE_LEG"
    LIMITS_OF_STABILITY = "LIMITS_OF_STABILITY"


class ProtocolValidationStatus(StrEnum):
    PILOT_REQUIRED = "PILOT_REQUIRED"
    VALIDATED = "VALIDATED"


@dataclass(frozen=True, slots=True)
class StartCondition:
    stable_hold_seconds: int
    requires_minimum_contact: bool = True
    requires_valid_area: bool = True


@dataclass(frozen=True, slots=True)
class EndCondition:
    ends_on_duration: bool = True
    operator_stop_marks_incomplete: bool = True
    device_failure_marks_incomplete: bool = True


@dataclass(frozen=True, slots=True)
class QualityGateProfile:
    gate_id: str
    version: str
    required_checks: tuple[str, ...]
    validation_status: ProtocolValidationStatus


@dataclass(frozen=True, slots=True)
class OperatorPromptConfig:
    position_text: str
    acquisition_text: str
    audio_enabled: bool
    countdown_cue_id: str | None = None
    start_cue_id: str | None = None
    finish_cue_id: str | None = None


@dataclass(frozen=True, slots=True)
class ScreeningProtocol:
    protocol_id: str
    version: str
    paradigm: ProtocolParadigm
    acquisition_duration_seconds: int
    start_condition: StartCondition
    end_condition: EndCondition
    quality_gate: QualityGateProfile
    prompts: OperatorPromptConfig
    validation_status: ProtocolValidationStatus

    def snapshot(self) -> ProtocolSnapshot:
        return ProtocolSnapshot(
            protocol_id=self.protocol_id,
            protocol_version=self.version,
            planned_duration_seconds=self.acquisition_duration_seconds,
            quality_gate_id=self.quality_gate.gate_id,
            quality_gate_version=self.quality_gate.version,
        )


@dataclass(frozen=True, slots=True)
class ProtocolSnapshot:
    protocol_id: str
    protocol_version: str
    planned_duration_seconds: int
    quality_gate_id: str
    quality_gate_version: str


def default_standard_protocol() -> ScreeningProtocol:
    """Pilot configuration; exact duration and thresholds require site validation."""

    return ScreeningProtocol(
        protocol_id="standard-static-bilateral",
        version="1.0.0-pilot",
        paradigm=ProtocolParadigm.STANDARD_BILATERAL,
        acquisition_duration_seconds=30,
        start_condition=StartCondition(stable_hold_seconds=3),
        end_condition=EndCondition(),
        quality_gate=QualityGateProfile(
            gate_id="static-basic-quality",
            version="1.0.0-pilot",
            required_checks=(
                "complete_session",
                "valid_duration",
                "sampling_integrity",
                "sensor_integrity",
                "minimum_contact",
                "valid_position_area",
                "calibration_eligible",
            ),
            validation_status=ProtocolValidationStatus.PILOT_REQUIRED,
        ),
        prompts=OperatorPromptConfig(
            position_text="双脚自然站立，保持身体放松",
            acquisition_text="请保持自然站立，不要说话或大幅移动",
            audio_enabled=False,
        ),
        validation_status=ProtocolValidationStatus.PILOT_REQUIRED,
    )


@dataclass(frozen=True, slots=True)
class FeatureFlags:
    enabled_protocol_ids: tuple[str, ...] = ()


class ProtocolUnavailable(RuntimeError):
    """Requested protocol is not validated and enabled for routine screening."""


class ProtocolCatalog:
    def __init__(self, protocols: tuple[ScreeningProtocol, ...]) -> None:
        self._protocols = protocols

    def select(
        self,
        paradigm: ProtocolParadigm,
        flags: FeatureFlags,
    ) -> ScreeningProtocol:
        protocol = next(
            (item for item in self._protocols if item.paradigm is paradigm),
            None,
        )
        if protocol is None:
            raise ProtocolUnavailable(f"protocol is not registered: {paradigm}")
        if paradigm is ProtocolParadigm.STANDARD_BILATERAL:
            return protocol
        if protocol.protocol_id not in flags.enabled_protocol_ids:
            raise ProtocolUnavailable("extended protocol feature is disabled")
        if protocol.validation_status is not ProtocolValidationStatus.VALIDATED:
            raise ProtocolUnavailable("extended protocol has not completed validation")
        return protocol


class ReferenceRangeApprovalStatus(StrEnum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"


@dataclass(frozen=True, slots=True)
class ReferenceRangeDefinition:
    range_id: str
    version: str
    applicable_population: str | None
    source: str | None
    approval_status: ReferenceRangeApprovalStatus
    approved_by: str | None = None
    approved_at: datetime | None = None

    @property
    def is_publishable(self) -> bool:
        return (
            self.approval_status is ReferenceRangeApprovalStatus.APPROVED
            and bool(self.version.strip())
            and bool(self.applicable_population and self.applicable_population.strip())
            and bool(self.source and self.source.strip())
            and bool(self.approved_by and self.approved_by.strip())
            and self.approved_at is not None
        )


class PositionStatus(StrEnum):
    WAITING = "WAITING"
    STABILIZING = "STABILIZING"
    READY = "READY"


@dataclass(frozen=True, slots=True)
class PositionGuidanceState:
    status: PositionStatus
    instruction_text: str
    countdown_seconds: int | None
    countdown_text: str
    manual_start_allowed: bool
    auto_start: bool = False


class PositionGuidanceController:
    def __init__(self, protocol: ScreeningProtocol) -> None:
        self._protocol = protocol
        self._stable_since: float | None = None
        self._auto_start_fired = False
        self._state = self._waiting_state()

    @property
    def state(self) -> PositionGuidanceState:
        return self._state

    def reset(self) -> None:
        self._stable_since = None
        self._auto_start_fired = False
        self._state = self._waiting_state()

    def observe(
        self,
        *,
        now_seconds: float,
        contact_ready: bool,
        in_valid_area: bool,
    ) -> PositionGuidanceState:
        if not contact_ready or not in_valid_area:
            self.reset()
            return self._state
        if self._stable_since is None:
            self._stable_since = now_seconds
        elapsed = max(0.0, now_seconds - self._stable_since)
        hold = self._protocol.start_condition.stable_hold_seconds
        if elapsed >= hold:
            fire_auto_start = not self._auto_start_fired
            self._auto_start_fired = True
            self._state = PositionGuidanceState(
                status=PositionStatus.READY,
                instruction_text=self._protocol.prompts.position_text,
                countdown_seconds=0,
                countdown_text="站位稳定，即将自动开始",
                manual_start_allowed=True,
                auto_start=fire_auto_start,
            )
            return self._state
        remaining = max(1, ceil(hold - elapsed))
        self._state = PositionGuidanceState(
            status=PositionStatus.STABILIZING,
            instruction_text=self._protocol.prompts.position_text,
            countdown_seconds=remaining,
            countdown_text=f"稳定中… {remaining} 秒后自动开始",
            manual_start_allowed=True,
        )
        return self._state

    def _waiting_state(self) -> PositionGuidanceState:
        return PositionGuidanceState(
            status=PositionStatus.WAITING,
            instruction_text=self._protocol.prompts.position_text,
            countdown_seconds=None,
            countdown_text="检测到稳定站位后将自动开始",
            manual_start_allowed=False,
        )
