"""Workflow-owned static-balance context, associated with a force session by ID.

This is intentionally not part of ``estimated-force-session/1.0``.  It is
provided by the screening workflow after operator confirmation and is hashed
into the immutable analysis-run identity.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from enum import StrEnum

from cloud.analysis.physical_input import PhysicalPressureSession


class ProtocolContextError(ValueError):
    """The workflow context is not a canonical static-balance protocol record."""


class StageId(StrEnum):
    BILATERAL_EYES_OPEN = "BILATERAL_EYES_OPEN"
    BILATERAL_EYES_CLOSED = "BILATERAL_EYES_CLOSED"
    SEMI_TANDEM_LEFT_FORWARD = "SEMI_TANDEM_LEFT_FORWARD"
    SEMI_TANDEM_RIGHT_FORWARD = "SEMI_TANDEM_RIGHT_FORWARD"


class CompletionStatus(StrEnum):
    COMPLETED = "COMPLETED"
    BALANCE_FAILURE = "BALANCE_FAILURE"
    SAFETY_ABORT = "SAFETY_ABORT"
    NON_BALANCE_STOP = "NON_BALANCE_STOP"
    PROTOCOL_INVALID = "PROTOCOL_INVALID"
    TECHNICAL_INVALID = "TECHNICAL_INVALID"


class SubjectOrientation(StrEnum):
    FORWARD = "FORWARD"
    LEFT_90 = "LEFT_90"


class ForwardFoot(StrEnum):
    NONE = "NONE"
    LEFT = "LEFT"
    RIGHT = "RIGHT"


class StopReason(StrEnum):
    NONE = "NONE"
    LOSS_OF_BALANCE = "LOSS_OF_BALANCE"
    SAFETY_SYMPTOM = "SAFETY_SYMPTOM"
    PAIN = "PAIN"
    INSTRUCTION = "INSTRUCTION"
    REFUSED = "REFUSED"
    TECHNICAL = "TECHNICAL"
    PROTOCOL = "PROTOCOL"
    OTHER = "OTHER"


@dataclass(frozen=True, slots=True)
class StageWindow:
    stage_id: StageId
    start_s: float
    end_s: float
    completion_status: CompletionStatus
    actual_completion_s: float
    subject_orientation: SubjectOrientation
    forward_foot: ForwardFoot
    step_count: int
    moved_feet: bool
    touched_rail: bool
    staff_supported: bool
    near_fall: bool
    eyes_opened_early: bool
    stop_reason: StopReason


@dataclass(frozen=True, slots=True)
class StaticBalanceProtocolContext:
    session_id: str
    protocol_version: str
    stages: tuple[StageWindow, ...]


_EXPECTED_STAGES = (
    StageId.BILATERAL_EYES_OPEN,
    StageId.BILATERAL_EYES_CLOSED,
    StageId.SEMI_TANDEM_LEFT_FORWARD,
    StageId.SEMI_TANDEM_RIGHT_FORWARD,
)


def validate_static_balance_protocol_context(
    context: StaticBalanceProtocolContext,
    *,
    session: PhysicalPressureSession | None = None,
) -> None:
    """Fail closed before protocol metadata can affect features or screening."""

    if not isinstance(context, StaticBalanceProtocolContext):
        raise ProtocolContextError("context must be StaticBalanceProtocolContext")
    if not context.session_id.strip() or not context.protocol_version.strip():
        raise ProtocolContextError("context session_id and protocol_version are required")
    if len(context.stages) != len(_EXPECTED_STAGES):
        raise ProtocolContextError("context must contain the canonical four stages")
    previous_end: float | None = None
    for index, stage in enumerate(context.stages):
        if stage.stage_id is not _EXPECTED_STAGES[index]:
            raise ProtocolContextError("stages must use the canonical four-stage order")
        if stage.start_s < 0 or stage.end_s <= stage.start_s:
            raise ProtocolContextError("stage bounds must be positive and ordered")
        if previous_end is not None and stage.start_s < previous_end:
            raise ProtocolContextError("stage windows must not overlap")
        previous_end = stage.end_s
        if not 0 <= stage.actual_completion_s <= stage.end_s - stage.start_s:
            raise ProtocolContextError("actual_completion_s must fit inside the stage window")
        expected_orientation = SubjectOrientation.FORWARD if index < 2 else SubjectOrientation.LEFT_90
        expected_foot = ForwardFoot.NONE if index < 2 else (ForwardFoot.LEFT if index == 2 else ForwardFoot.RIGHT)
        if stage.subject_orientation is not expected_orientation or stage.forward_foot is not expected_foot:
            raise ProtocolContextError("stage orientation or forward foot is invalid")
        if stage.step_count < 0:
            raise ProtocolContextError("step_count must be non-negative")
    if session is not None:
        if context.session_id != session.session_id:
            raise ProtocolContextError("protocol context session identity does not match physical session")
        if context.stages[0].start_s < session.frames[0].timestamp_s or context.stages[-1].end_s > session.frames[-1].timestamp_s:
            raise ProtocolContextError("stage bounds must fit within physical session time")


def protocol_context_sha256(context: StaticBalanceProtocolContext) -> str:
    """Deterministic identity used in versioned re-runs."""

    validate_static_balance_protocol_context(context)
    encoded = json.dumps(
        asdict(context), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
