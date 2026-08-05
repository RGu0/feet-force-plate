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
class ProtocolStage:
    """One scored V1 static-balance action inside a single screening session."""

    stage_id: str
    operator_title: str
    position_text: str
    acquisition_text: str
    duration_seconds: int

    def __post_init__(self) -> None:
        if not self.stage_id or self.duration_seconds <= 0:
            raise ValueError("stage id and positive duration are required")


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
    stages: tuple[ProtocolStage, ...]

    def snapshot(self) -> ProtocolSnapshot:
        return ProtocolSnapshot(
            protocol_id=self.protocol_id,
            protocol_version=self.version,
            planned_duration_seconds=self.acquisition_duration_seconds,
            quality_gate_id=self.quality_gate.gate_id,
            quality_gate_version=self.quality_gate.version,
            stage_ids=tuple(stage.stage_id for stage in self.stages),
        )


@dataclass(frozen=True, slots=True)
class ProtocolSnapshot:
    protocol_id: str
    protocol_version: str
    planned_duration_seconds: int
    quality_gate_id: str
    quality_gate_version: str
    stage_ids: tuple[str, ...] = ()


def default_standard_protocol() -> ScreeningProtocol:
    """Pilot configuration; exact duration and thresholds require site validation."""

    return ScreeningProtocol(
        protocol_id="standard-static-bilateral",
        version="v1-replay-debug/1.0.1",
        paradigm=ProtocolParadigm.STANDARD_BILATERAL,
        acquisition_duration_seconds=80,
        start_condition=StartCondition(
            stable_hold_seconds=0,
            requires_minimum_contact=False,
            requires_valid_area=False,
        ),
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
        stages=(
            ProtocolStage(
                "BILATERAL_EYES_OPEN",
                "第一段：并足睁眼",
                "双脚并拢自然站立，睁眼平视前方",
                "请保持并足睁眼站立，不要说话或大幅移动",
                20,
            ),
            ProtocolStage(
                "BILATERAL_EYES_CLOSED",
                "第二段：并足闭眼",
                "双脚并拢自然站立，确认安全后闭眼",
                "请保持并足闭眼站立，工作人员请在旁保护",
                20,
            ),
            ProtocolStage(
                "SEMI_TANDEM_LEFT_FORWARD",
                "第三段：左脚在前半串联",
                "左脚在前、右脚在后，保持半串联站位",
                "请保持左脚在前半串联站位",
                20,
            ),
            ProtocolStage(
                "SEMI_TANDEM_RIGHT_FORWARD",
                "第四段：右脚在前半串联",
                "右脚在前、左脚在后，保持半串联站位",
                "请保持右脚在前半串联站位",
                20,
            ),
        ),
    )


@dataclass(frozen=True, slots=True)
class FeatureFlags:
    enabled_protocol_ids: tuple[str, ...] = ()
    allow_pilot_protocols_for_replay_debug: bool = False


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
        if protocol.validation_status is ProtocolValidationStatus.PILOT_REQUIRED:
            if (
                flags.allow_pilot_protocols_for_replay_debug
                and protocol.protocol_id in flags.enabled_protocol_ids
            ):
                return protocol
            raise ProtocolUnavailable("pilot protocol is unavailable for institution screening")
        if protocol.protocol_id not in flags.enabled_protocol_ids:
            raise ProtocolUnavailable("protocol feature is disabled")
        if protocol.validation_status is not ProtocolValidationStatus.VALIDATED:
            raise ProtocolUnavailable("protocol has not completed validation")
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
        self._stage: ProtocolStage | None = None
        self._stable_since: float | None = None
        self._state = self._waiting_state()

    @property
    def state(self) -> PositionGuidanceState:
        return self._state

    def reset(self) -> None:
        self._stable_since = None
        self._state = self._waiting_state()

    def set_stage(self, stage: ProtocolStage) -> None:
        self._stage = stage
        self.reset()

    def observe(
        self,
        *,
        now_seconds: float,
        contact_ready: bool,
        in_valid_area: bool,
    ) -> PositionGuidanceState:
        condition = self._protocol.start_condition
        if (
            condition.requires_minimum_contact and not contact_ready
        ) or (
            condition.requires_valid_area and not in_valid_area
        ):
            self.reset()
            return self._state
        if self._stable_since is None:
            self._stable_since = now_seconds
        elapsed = max(0.0, now_seconds - self._stable_since)
        hold = condition.stable_hold_seconds
        if elapsed >= hold:
            self._state = self._ready_state()
            return self._state
        remaining = max(1, ceil(hold - elapsed))
        self._state = PositionGuidanceState(
            status=PositionStatus.STABILIZING,
            instruction_text=self._position_text(),
            countdown_seconds=remaining,
            countdown_text=f"正在确认站位稳定… {remaining} 秒",
            manual_start_allowed=False,
        )
        return self._state

    def _waiting_state(self) -> PositionGuidanceState:
        condition = self._protocol.start_condition
        if (
            condition.stable_hold_seconds == 0
            and not condition.requires_minimum_contact
            and not condition.requires_valid_area
        ):
            return self._ready_state()
        return PositionGuidanceState(
            status=PositionStatus.WAITING,
            instruction_text=self._position_text(),
            countdown_seconds=None,
            countdown_text="请按指引调整站位，稳定后再开始本段",
            manual_start_allowed=False,
        )

    def _ready_state(self) -> PositionGuidanceState:
        return PositionGuidanceState(
            status=PositionStatus.READY,
            instruction_text=self._position_text(),
            countdown_seconds=None,
            countdown_text="操作员确认站位和安全后，请点击“开始本段”",
            manual_start_allowed=True,
            auto_start=False,
        )

    def _position_text(self) -> str:
        return self._stage.position_text if self._stage is not None else self._protocol.prompts.position_text
