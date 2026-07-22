from __future__ import annotations

from dataclasses import dataclass

from cloud.analysis.features import SessionFeatureSet
from cloud.analysis.models import CapabilityDecision, CapabilityStatus, ValidationStatus
from cloud.analysis.physical_input import PhysicalPressureSession, ValidationState


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
        "contact_area_variation_mm2",
        "eyes_closed_change",
        "semi_tandem_challenge",
        "front_foot_difference",
    }
)


@dataclass(frozen=True, slots=True)
class PhysicalMetricDescriptor:
    metric_id: str
    unit: str
    definition: str
    input_schema_version: str
    measurement_conformance_version: str
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
    if session.coordinate_frame.value != "SUBJECT_ML_AP":
        reasons.append("COORDINATE_FRAME_UNSUPPORTED")
    if (session.coordinate_unit, session.force_unit, session.area_unit, session.time_unit) != (
        "mm",
        "N",
        "mm2",
        "s",
    ):
        reasons.append("PHYSICAL_UNITS_UNSUPPORTED")
    profile = session.measurement_profile
    if any(
        value is not ValidationState.VALIDATED
        for value in (
            profile.physical_validation,
            profile.timing_validation,
            profile.coordinate_validation,
        )
    ):
        reasons.append("MEASUREMENT_VALIDATION_INSUFFICIENT")
    if profile.measurement_conformance_version != descriptor.measurement_conformance_version:
        reasons.append("MEASUREMENT_CONFORMANCE_MISMATCH")
    if profile.uncertainty_profile_version != descriptor.uncertainty_profile_version:
        reasons.append("UNCERTAINTY_PROFILE_MISMATCH")
    if features.pipeline_version != descriptor.feature_pipeline_version:
        reasons.append("FEATURE_PIPELINE_MISMATCH")
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
