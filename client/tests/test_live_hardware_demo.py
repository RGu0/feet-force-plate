from __future__ import annotations

import pytest

from client.app.live_hardware_demo import (
    OperatorStageAttestation,
    build_operator_attested_protocol,
    is_basic_report_eligible,
    operator_attestations_from_completion_flags,
    static_balance_stage_plan,
)
from cloud.analysis.protocol_context import (
    CompletionStatus,
    StageId,
    StopReason,
)


def test_static_balance_stage_plan_is_the_canonical_four_stage_sequence() -> None:
    plan = static_balance_stage_plan(stage_seconds=20.0)

    assert [stage.stage_id for stage in plan] == [
        StageId.BILATERAL_EYES_OPEN,
        StageId.BILATERAL_EYES_CLOSED,
        StageId.SEMI_TANDEM_LEFT_FORWARD,
        StageId.SEMI_TANDEM_RIGHT_FORWARD,
    ]
    assert [(stage.start_s, stage.end_s) for stage in plan] == [
        (0.0, 20.0),
        (20.0, 40.0),
        (40.0, 60.0),
        (60.0, 80.0),
    ]


def test_operator_attested_protocol_preserves_noncompleted_stage() -> None:
    plan = static_balance_stage_plan(stage_seconds=20.0)
    attestations = tuple(
        OperatorStageAttestation(
            stage_id=stage.stage_id,
            completion_status=(
                CompletionStatus.BALANCE_FAILURE
                if stage.stage_id is StageId.BILATERAL_EYES_CLOSED
                else CompletionStatus.COMPLETED
            ),
            stop_reason=(
                StopReason.LOSS_OF_BALANCE
                if stage.stage_id is StageId.BILATERAL_EYES_CLOSED
                else StopReason.NONE
            ),
            step_count=0,
            moved_feet=False,
            touched_rail=False,
            staff_supported=False,
            near_fall=False,
            eyes_opened_early=False,
        )
        for stage in plan
    )

    context = build_operator_attested_protocol(
        session_id="physical-demo-1",
        stage_seconds=20.0,
        attestations=attestations,
    )

    assert context.session_id == "physical-demo-1"
    assert context.stages[1].completion_status is CompletionStatus.BALANCE_FAILURE
    assert context.stages[1].stop_reason is StopReason.LOSS_OF_BALANCE
    assert is_basic_report_eligible(context) is False


def test_operator_attested_protocol_rejects_missing_or_wrong_stage_attestation() -> None:
    with pytest.raises(ValueError, match="canonical four-stage"):
        build_operator_attested_protocol(
            session_id="physical-demo-1",
            stage_seconds=20.0,
            attestations=(),
        )


def test_completion_flags_never_turn_a_failed_stage_into_a_report_eligible_one() -> None:
    plan = static_balance_stage_plan(stage_seconds=20.0)
    context = build_operator_attested_protocol(
        session_id="physical-demo-2",
        stage_seconds=20.0,
        attestations=operator_attestations_from_completion_flags(
            plan,
            (True, False, True, True),
        ),
    )

    assert context.stages[1].completion_status is CompletionStatus.PROTOCOL_INVALID
    assert is_basic_report_eligible(context) is False
