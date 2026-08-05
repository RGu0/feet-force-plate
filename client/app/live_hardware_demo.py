"""Operator-attested static-balance context for the live hardware demo.

This module deliberately does not infer participant behaviour from pressure
frames.  A supervising operator must record the outcome of every stage before
the committed hardware session is eligible for local analysis.
"""

from __future__ import annotations

from dataclasses import dataclass

from client.device.stage_windows import (
    CapturedStageWindow,
    validate_captured_stage_windows,
)
from cloud.analysis.protocol_context import (
    CompletionStatus,
    ForwardFoot,
    StageId,
    StageWindow,
    StaticBalanceProtocolContext,
    StopReason,
    SubjectOrientation,
)


@dataclass(frozen=True, slots=True)
class OperatorStageAttestation:
    """The supervisor's observation for one timed, real-hardware stage."""

    stage_id: StageId
    completion_status: CompletionStatus
    stop_reason: StopReason
    step_count: int
    moved_feet: bool
    touched_rail: bool
    staff_supported: bool
    near_fall: bool
    eyes_opened_early: bool

    def __post_init__(self) -> None:
        if self.step_count < 0:
            raise ValueError("step_count must be non-negative")


def static_balance_stage_plan(*, stage_seconds: float) -> tuple[StageWindow, ...]:
    """Return the canonical four timed stages without claiming observations."""

    if stage_seconds <= 0:
        raise ValueError("stage_seconds must be positive")
    definitions = (
        (StageId.BILATERAL_EYES_OPEN, SubjectOrientation.FORWARD, ForwardFoot.NONE),
        (StageId.BILATERAL_EYES_CLOSED, SubjectOrientation.FORWARD, ForwardFoot.NONE),
        (
            StageId.SEMI_TANDEM_LEFT_FORWARD,
            SubjectOrientation.LEFT_90,
            ForwardFoot.LEFT,
        ),
        (
            StageId.SEMI_TANDEM_RIGHT_FORWARD,
            SubjectOrientation.LEFT_90,
            ForwardFoot.RIGHT,
        ),
    )
    return tuple(
        StageWindow(
            stage_id=stage_id,
            start_s=index * stage_seconds,
            end_s=(index + 1) * stage_seconds,
            completion_status=CompletionStatus.PROTOCOL_INVALID,
            actual_completion_s=0.0,
            subject_orientation=orientation,
            forward_foot=forward_foot,
            step_count=0,
            moved_feet=False,
            touched_rail=False,
            staff_supported=False,
            near_fall=False,
            eyes_opened_early=False,
            stop_reason=StopReason.PROTOCOL,
        )
        for index, (stage_id, orientation, forward_foot) in enumerate(definitions)
    )


def build_operator_attested_protocol(
    *,
    session_id: str,
    stage_seconds: float,
    attestations: tuple[OperatorStageAttestation, ...],
    captured_windows: tuple[CapturedStageWindow, ...] | None = None,
) -> StaticBalanceProtocolContext:
    """Build context only from four explicit supervisor attestations."""

    if not session_id:
        raise ValueError("session_id is required")
    plan = static_balance_stage_plan(stage_seconds=stage_seconds)
    if len(attestations) != len(plan) or any(
        attestation.stage_id is not stage.stage_id
        for attestation, stage in zip(attestations, plan)
    ):
        raise ValueError("attestations must use the canonical four-stage order")
    if captured_windows is not None:
        captured_windows = validate_captured_stage_windows(
            captured_windows,
            expected_stage_ids=tuple(stage.stage_id.value for stage in plan),
            minimum_duration_s=stage_seconds,
        )
    stages = tuple(
        StageWindow(
            stage_id=stage.stage_id,
            start_s=(
                captured_window.start_s if captured_window is not None else stage.start_s
            ),
            end_s=(
                captured_window.end_s if captured_window is not None else stage.end_s
            ),
            completion_status=attestation.completion_status,
            actual_completion_s=(
                stage_seconds
                if attestation.completion_status is CompletionStatus.COMPLETED
                else 0.0
            ),
            subject_orientation=stage.subject_orientation,
            forward_foot=stage.forward_foot,
            step_count=attestation.step_count,
            moved_feet=attestation.moved_feet,
            touched_rail=attestation.touched_rail,
            staff_supported=attestation.staff_supported,
            near_fall=attestation.near_fall,
            eyes_opened_early=attestation.eyes_opened_early,
            stop_reason=attestation.stop_reason,
        )
        for stage, attestation, captured_window in zip(
            plan,
            attestations,
            captured_windows if captured_windows is not None else (None,) * len(plan),
        )
    )
    return StaticBalanceProtocolContext(
        session_id=session_id,
        protocol_version="static-balance/live-hardware-demo/1",
        stages=stages,
    )


def operator_attestations_from_completion_flags(
    plan: tuple[StageWindow, ...],
    completed: tuple[bool, ...],
) -> tuple[OperatorStageAttestation, ...]:
    """Turn explicit supervisor confirmations into fail-closed attestations."""

    if len(completed) != len(plan):
        raise ValueError("completion confirmations must cover every stage")
    return tuple(
        OperatorStageAttestation(
            stage_id=stage.stage_id,
            completion_status=(
                CompletionStatus.COMPLETED
                if confirmation
                else CompletionStatus.PROTOCOL_INVALID
            ),
            stop_reason=StopReason.NONE if confirmation else StopReason.PROTOCOL,
            step_count=0,
            moved_feet=False,
            touched_rail=False,
            staff_supported=False,
            near_fall=False,
            eyes_opened_early=False,
        )
        for stage, confirmation in zip(plan, completed)
    )


def is_basic_report_eligible(context: StaticBalanceProtocolContext) -> bool:
    """Require an uneventful, explicitly attested four-stage observation."""

    return all(
        stage.completion_status is CompletionStatus.COMPLETED
        and stage.stop_reason is StopReason.NONE
        and not stage.moved_feet
        and not stage.touched_rail
        and not stage.staff_supported
        and not stage.near_fall
        and not stage.eyes_opened_early
        for stage in context.stages
    )
