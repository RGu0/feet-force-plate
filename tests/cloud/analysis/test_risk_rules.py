from __future__ import annotations

from dataclasses import replace

from cloud.analysis.feature_parameters import FeatureParameters
from cloud.analysis.features import extract_features
from cloud.analysis.physical_input import PhysicalInputValidationStatus, parse_physical_pressure_session
from cloud.analysis.protocol_context import CompletionStatus, StopReason
from cloud.analysis.risk_rules import (
    BackgroundRisk,
    MedicationTag,
    QuestionnaireSnapshot,
    RiskTier,
    evaluate_screening_risk,
)

from test_physical_features import _session_payload
from test_physical_input import valid_protocol_context


def features():
    return extract_features(
        parse_physical_pressure_session(_session_payload()),
        valid_protocol_context(),
        FeatureParameters(version="physical-features/test", lowpass_cutoff_hz=0.0),
    )


def questionnaire(**overrides: object) -> QuestionnaireSnapshot:
    values: dict[str, object] = {
        "age_years": 72,
        "recent_fall_12m": False,
        "recurrent_dizziness": False,
        "medication_tags": frozenset(),
    }
    values.update(overrides)
    return QuestionnaireSnapshot(**values)


def test_explicit_background_high_risk_wins_over_good_balance() -> None:
    result = evaluate_screening_risk(
        protocol_context=valid_protocol_context(),
        input_validation_status=PhysicalInputValidationStatus.VALIDATED,
        features=features(),
        questionnaire=questionnaire(recent_fall_12m=True),
    )

    assert result.risk_tier is RiskTier.HIGH
    assert result.balance_index <= 59
    assert "RECENT_FALL_12M" in result.background_reason_codes


def test_single_semi_tandem_failure_is_medium_risk_evidence() -> None:
    context = valid_protocol_context()
    stages = list(context.stages)
    stages[2] = replace(
        stages[2], completion_status=CompletionStatus.BALANCE_FAILURE,
        actual_completion_s=4.0, stop_reason=StopReason.LOSS_OF_BALANCE,
    )
    result = evaluate_screening_risk(
        protocol_context=replace(context, stages=tuple(stages)),
        input_validation_status=PhysicalInputValidationStatus.VALIDATED,
        features=features(),
        questionnaire=questionnaire(),
    )

    assert result.risk_tier is RiskTier.MEDIUM
    assert result.balance_index <= 79
    assert "BALANCE_FAILURE" in result.completion_reason_codes


def test_unknown_background_is_not_treated_as_no() -> None:
    result = evaluate_screening_risk(
        protocol_context=valid_protocol_context(),
        input_validation_status=PhysicalInputValidationStatus.VALIDATED,
        features=features(),
        questionnaire=questionnaire(recent_fall_12m=None, recurrent_dizziness=None),
    )

    assert result.risk_tier in {RiskTier.MEDIUM, RiskTier.INSUFFICIENT_DATA}
    assert result.background_status is BackgroundRisk.UNKNOWN


def test_unknown_age_does_not_emit_a_composite_score() -> None:
    result = evaluate_screening_risk(
        protocol_context=valid_protocol_context(),
        input_validation_status=PhysicalInputValidationStatus.VALIDATED,
        features=features(),
        questionnaire=questionnaire(age_years=None),
    )

    assert result.risk_tier is RiskTier.INSUFFICIENT_DATA
    assert result.balance_index == 0


def test_medication_categories_are_optional_labels_only() -> None:
    result = evaluate_screening_risk(
        protocol_context=valid_protocol_context(),
        input_validation_status=PhysicalInputValidationStatus.VALIDATED,
        features=features(),
        questionnaire=questionnaire(
            medication_tags=frozenset({MedicationTag.SEDATIVE_HYPNOTIC})
        ),
    )

    assert result.risk_tier is RiskTier.MEDIUM
    assert "MEDICATION_CATEGORY_PRESENT" in result.background_reason_codes
    assert result.private_trace == ()
