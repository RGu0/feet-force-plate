from __future__ import annotations

from dataclasses import dataclass

from cloud.analysis.features import SessionFeatureSet
from cloud.analysis.models import CapabilityDecision, CapabilityStatus, ValidationStatus
from cloud.analysis.physical_input import PhysicalPressureSession
from cloud.analysis.physical_input import PhysicalInputValidationStatus


V1_STATIC_BALANCE_METRICS = frozenset(
    {
        "cop_path_mm",
        "total_mean_velocity_mm_s",
        "ml_mean_velocity_mm_s",
        "ap_mean_velocity_mm_s",
        "ml_rms_mm",
        "ap_rms_mm",
        "ml_range_90_mm",
        "ap_range_90_mm",
        "ellipse_area_95_mm2",
        "total_force_cv",
        "eyes_closed_change",
        "semi_tandem_challenge",
        "front_foot_difference",
    }
)

RISK_RELEASE_REQUIRED_METRICS = frozenset({"ellipse_area_95_mm2"})


@dataclass(frozen=True, slots=True)
class PhysicalMetricDescriptor:
    metric_id: str
    unit: str
    definition: str
    input_schema_version: str
    measurement_conformance_version: str
    calibration_profile_version: str
    uncertainty_profile_version: str
    protocol_version: str
    feature_pipeline_version: str
    feature_parameters_sha256: str
    algorithm_version: str
    validation_status: ValidationStatus
    reference_artifact_sha256: str
    approved_adapter_version: str


@dataclass(frozen=True, slots=True)
class PhysicalCapabilityContext:
    sample_rate_hz: float
    valid_frame_ratio: float
    completed_valid_duration_s: float
    max_gap_nominal_intervals: float
    reference_artifact_sha256: str | None
    adapter_version: str
    measurement_conformance_version: str
    calibration_profile_version: str
    uncertainty_profile_version: str
    input_validation_status: PhysicalInputValidationStatus
    protocol_version: str
    rule_set_version: str


def evaluate_physical_capability(
    *,
    session: PhysicalPressureSession,
    features: SessionFeatureSet,
    context: PhysicalCapabilityContext,
    descriptor: PhysicalMetricDescriptor,
) -> CapabilityDecision:
    """Default-closed capability gate for V1 physical static-balance metrics."""

    reasons: list[str] = []
    if descriptor.metric_id not in V1_STATIC_BALANCE_METRICS:
        reasons.append("METRIC_NOT_IN_V1_WHITELIST")
    if session.schema_version != descriptor.input_schema_version:
        reasons.append("INPUT_SCHEMA_MISMATCH")
    if session.coordinate_frame.value != "BOARD_TOP_LEFT_X_RIGHT_Y_DOWN":
        reasons.append("COORDINATE_FRAME_UNSUPPORTED")
    if (session.coordinate_unit, session.force_unit, session.time_unit) != (
        "mm",
        "N",
        "s",
    ):
        reasons.append("PHYSICAL_UNITS_UNSUPPORTED")
    if context.input_validation_status is not PhysicalInputValidationStatus.VALIDATED:
        reasons.append("PHYSICAL_INPUT_NOT_VALIDATED")
    if context.measurement_conformance_version != descriptor.measurement_conformance_version:
        reasons.append("MEASUREMENT_CONFORMANCE_MISMATCH")
    if context.calibration_profile_version != descriptor.calibration_profile_version:
        reasons.append("CALIBRATION_PROFILE_MISMATCH")
    if context.uncertainty_profile_version != descriptor.uncertainty_profile_version:
        reasons.append("UNCERTAINTY_PROFILE_MISMATCH")
    if features.pipeline_version != descriptor.feature_pipeline_version:
        reasons.append("FEATURE_PIPELINE_MISMATCH")
    if features.parameters_sha256 != descriptor.feature_parameters_sha256:
        reasons.append("FEATURE_PARAMETERS_MISMATCH")
    if context.protocol_version != descriptor.protocol_version:
        reasons.append("PROTOCOL_VERSION_MISMATCH")
    if context.rule_set_version != descriptor.algorithm_version:
        reasons.append("RULE_SET_VERSION_MISMATCH")
    if context.sample_rate_hz < 18.0:
        reasons.append("SAMPLE_RATE_TOO_LOW")
    if context.completed_valid_duration_s < 19.0 or any(
        stage.completion_time_s < 19.0 for stage in features.stages
    ):
        reasons.append("DURATION_TOO_SHORT")
    if context.valid_frame_ratio < 0.95:
        reasons.append("VALID_FRAME_RATIO_TOO_LOW")
    if context.max_gap_nominal_intervals > 2.0:
        reasons.append("GAP_TOO_LARGE")
    if context.reference_artifact_sha256 is None:
        reasons.append("REFERENCE_ARTIFACT_NOT_APPROVED")
    elif context.reference_artifact_sha256 != descriptor.reference_artifact_sha256:
        reasons.append("REFERENCE_ARTIFACT_MISMATCH")
    if context.adapter_version != descriptor.approved_adapter_version:
        reasons.append("ADAPTER_APPROVAL_STALE")
    if descriptor.validation_status is not ValidationStatus.APPROVED:
        reasons.append("ALGORITHM_NOT_APPROVED")

    return CapabilityDecision(
        metric_id=descriptor.metric_id,
        status=CapabilityStatus.SUPPORTED if not reasons else CapabilityStatus.UNSUPPORTED,
        internal_reason_codes=tuple(reasons),
    )


def evaluate_risk_release_capability(
    *,
    session: PhysicalPressureSession,
    features: SessionFeatureSet,
    context: PhysicalCapabilityContext,
    descriptor: PhysicalMetricDescriptor,
) -> CapabilityDecision:
    """Gate the public V1 composite on the exact feature bundle it consumes."""

    decision = evaluate_physical_capability(
        session=session,
        features=features,
        context=context,
        descriptor=descriptor,
    )
    if descriptor.metric_id in RISK_RELEASE_REQUIRED_METRICS:
        return decision
    return CapabilityDecision(
        metric_id=decision.metric_id,
        status=CapabilityStatus.UNSUPPORTED,
        internal_reason_codes=decision.internal_reason_codes
        + ("RISK_RELEASE_METRIC_BUNDLE_MISMATCH",),
    )
