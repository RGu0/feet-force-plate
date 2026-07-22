from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from cloud.analysis.features import SessionFeatureSet
from cloud.analysis.physical_input import (
    CompletionStatus,
    PhysicalPressureSession,
    StageId,
    ValidationState,
)


class MedicationTag(StrEnum):
    """Optional medication categories; no drug names, dose, or free text."""

    SEDATIVE_HYPNOTIC = "SEDATIVE_HYPNOTIC"
    PSYCHOTROPIC = "PSYCHOTROPIC"
    OPIOID_ANALGESIC = "OPIOID_ANALGESIC"
    BLOOD_PRESSURE_LOWERING = "BLOOD_PRESSURE_LOWERING"


class RiskTier(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    TECHNICAL_INVALID = "TECHNICAL_INVALID"


class BackgroundRisk(StrEnum):
    CLEAR = "CLEAR"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class QuestionnaireSnapshot:
    age_years: int | None
    recent_fall_12m: bool | None
    recurrent_dizziness: bool | None
    medication_tags: frozenset[MedicationTag]

    def __post_init__(self) -> None:
        if self.age_years is not None and self.age_years < 0:
            raise ValueError("age_years cannot be negative")
        if not self.medication_tags.issubset(frozenset(MedicationTag)):
            raise ValueError("unsupported medication category")


def questionnaire_snapshot_sha256(questionnaire: QuestionnaireSnapshot) -> str:
    """Return the deterministic identity digest stored on an AnalysisRun key."""

    payload = {
        "age_years": questionnaire.age_years,
        "recent_fall_12m": questionnaire.recent_fall_12m,
        "recurrent_dizziness": questionnaire.recurrent_dizziness,
        "medication_tags": sorted(tag.value for tag in questionnaire.medication_tags),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class ScreeningRiskResult:
    risk_tier: RiskTier
    balance_index: int
    background_status: BackgroundRisk
    background_reason_codes: tuple[str, ...]
    completion_reason_codes: tuple[str, ...]
    balance_reason_codes: tuple[str, ...]
    private_trace: tuple[str, ...] = ()


def _score_from_features(features: SessionFeatureSet) -> tuple[int, tuple[str, ...]]:
    """Return a provisional 0-100 index; thresholds are versioned with this rule set."""

    penalties = 0
    reasons: list[str] = []
    eyes_ratio = features.eyes_closed_ratio("ellipse_area_95_mm2")
    semi_left = features.semi_tandem_ratio(
        StageId.SEMI_TANDEM_LEFT_FORWARD, "ellipse_area_95_mm2"
    )
    semi_right = features.semi_tandem_ratio(
        StageId.SEMI_TANDEM_RIGHT_FORWARD, "ellipse_area_95_mm2"
    )
    side_difference = features.side_difference("ellipse_area_95_mm2")
    # These are screening thresholds, not medical cut-offs. The reference artifact
    # gate must replace them before formal pressure grading is released.
    if eyes_ratio >= 2.5:
        penalties += 25
        reasons.append("EYES_CLOSED_SWAY_LARGE")
    elif eyes_ratio >= 1.75:
        penalties += 10
        reasons.append("EYES_CLOSED_SWAY_ELEVATED")
    if max(semi_left, semi_right) >= 3.5:
        penalties += 25
        reasons.append("SEMI_TANDEM_CHALLENGE_LARGE")
    elif max(semi_left, semi_right) >= 2.5:
        penalties += 10
        reasons.append("SEMI_TANDEM_CHALLENGE_ELEVATED")
    if side_difference >= 0.7:
        penalties += 25
        reasons.append("FRONT_FOOT_ASYMMETRY_LARGE")
    elif side_difference >= 0.45:
        penalties += 10
        reasons.append("FRONT_FOOT_ASYMMETRY_ELEVATED")
    score = max(0, min(100, 100 - penalties))
    return score, tuple(reasons)


def evaluate_screening_risk(
    *,
    session: PhysicalPressureSession,
    features: SessionFeatureSet,
    questionnaire: QuestionnaireSnapshot,
) -> ScreeningRiskResult:
    """Apply V1 rule-first risk logic; no fixed weighted average is used."""

    if questionnaire.age_years is None or questionnaire.age_years < 60:
        return ScreeningRiskResult(
            risk_tier=RiskTier.INSUFFICIENT_DATA,
            balance_index=0,
            background_status=BackgroundRisk.UNKNOWN,
            background_reason_codes=("AGE_BELOW_V1_THRESHOLD",),
            completion_reason_codes=(),
            balance_reason_codes=(),
        )

    profile = session.measurement_profile
    if any(
        state is not ValidationState.VALIDATED
        for state in (
            profile.physical_validation,
            profile.timing_validation,
            profile.coordinate_validation,
            profile.force_validation,
            profile.geometry_validation,
        )
    ):
        return ScreeningRiskResult(
            risk_tier=RiskTier.TECHNICAL_INVALID,
            balance_index=0,
            background_status=BackgroundRisk.UNKNOWN,
            background_reason_codes=(),
            completion_reason_codes=("TECHNICAL_VALIDATION_FAILED",),
            balance_reason_codes=(),
        )

    background_reasons: list[str] = []
    if questionnaire.recent_fall_12m is True:
        background_reasons.append("RECENT_FALL_12M")
    if questionnaire.recurrent_dizziness is True:
        background_reasons.append("RECURRENT_DIZZINESS")
    if questionnaire.medication_tags:
        background_reasons.append("MEDICATION_CATEGORY_PRESENT")
    if any(value is None for value in (questionnaire.recent_fall_12m, questionnaire.recurrent_dizziness)):
        background_status = BackgroundRisk.UNKNOWN
    elif background_reasons and any(
        reason in background_reasons for reason in ("RECENT_FALL_12M", "RECURRENT_DIZZINESS")
    ):
        background_status = BackgroundRisk.HIGH
    elif questionnaire.medication_tags:
        background_status = BackgroundRisk.MEDIUM
    else:
        background_status = BackgroundRisk.CLEAR

    completion_reasons: list[str] = []
    balance_failures = 0
    severe_completion = False
    for stage in session.stages:
        if stage.completion_status in {CompletionStatus.BALANCE_FAILURE, CompletionStatus.SAFETY_ABORT}:
            completion_reasons.append(stage.completion_status.value)
            balance_failures += 1
        elif stage.completion_status is not CompletionStatus.COMPLETED:
            completion_reasons.append(f"{stage.stage_id.value}:INCOMPLETE")
        if stage.touched_rail or stage.staff_supported or stage.near_fall:
            severe_completion = True
            completion_reasons.append(f"{stage.stage_id.value}:SAFETY_SUPPORT")
    if any(
        stage.completion_status in {CompletionStatus.TECHNICAL_INVALID, CompletionStatus.PROTOCOL_INVALID}
        for stage in session.stages
    ):
        return ScreeningRiskResult(
            risk_tier=RiskTier.TECHNICAL_INVALID,
            balance_index=0,
            background_status=background_status,
            background_reason_codes=tuple(background_reasons),
            completion_reason_codes=tuple(completion_reasons) + ("PROTOCOL_OR_TECHNICAL_INVALID",),
            balance_reason_codes=(),
        )
    score, balance_reasons = _score_from_features(features)

    if severe_completion or balance_failures >= 2:
        tier = RiskTier.HIGH
        score = min(score, 59)
    elif balance_failures == 1:
        tier = RiskTier.MEDIUM
        score = min(score, 79)
    elif background_status is BackgroundRisk.HIGH:
        tier = RiskTier.HIGH
        score = min(score, 59)
    elif score < 60:
        tier = RiskTier.HIGH
    elif background_status is BackgroundRisk.MEDIUM:
        tier = RiskTier.MEDIUM
        score = min(score, 79)
    elif background_status is BackgroundRisk.UNKNOWN:
        tier = RiskTier.INSUFFICIENT_DATA
        score = min(score, 79)
    elif score < 80:
        tier = RiskTier.MEDIUM
    else:
        tier = RiskTier.LOW

    return ScreeningRiskResult(
        risk_tier=tier,
        balance_index=score,
        background_status=background_status,
        background_reason_codes=tuple(background_reasons),
        completion_reason_codes=tuple(completion_reasons),
        balance_reason_codes=balance_reasons,
    )
