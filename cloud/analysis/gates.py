from __future__ import annotations

from cloud.analysis.models import (
    AlgorithmDescriptor,
    CapabilityDecision,
    CapabilityStatus,
    SessionContext,
    ValidationStatus,
    calibration_rank,
)


def evaluate_capability(
    context: SessionContext,
    descriptor: AlgorithmDescriptor,
) -> CapabilityDecision:
    reasons: list[str] = []

    if context.manifest_status != "VERIFIED":
        reasons.append("MANIFEST_NOT_VERIFIED")
    if context.validity_status != "VALID":
        reasons.append("SESSION_NOT_VALID")
    if context.cloud_quality_status != "PASS":
        reasons.append("CLOUD_QUALITY_FAILED")
    for quality_flag in sorted(context.quality_flags & descriptor.blocked_quality_flags):
        reasons.append(f"QUALITY_FLAG_BLOCKED:{quality_flag}")
    if context.actual_sample_rate_hz < descriptor.required_sample_rate_hz:
        reasons.append("SAMPLE_RATE_TOO_LOW")
    if calibration_rank(context.calibration_level) < calibration_rank(
        descriptor.required_calibration_level
    ):
        reasons.append("CALIBRATION_INSUFFICIENT")
    if context.duration_seconds < descriptor.required_duration_seconds:
        reasons.append("DURATION_TOO_SHORT")
    if (
        descriptor.required_test_protocols
        and context.test_protocol_id not in descriptor.required_test_protocols
    ):
        reasons.append("PROTOCOL_UNSUPPORTED")
    if not descriptor.required_profile_fields.issubset(context.profile_fields):
        reasons.append("PROFILE_FIELDS_MISSING")
    if (
        descriptor.supported_device_models
        and context.device_model not in descriptor.supported_device_models
    ):
        reasons.append("DEVICE_UNSUPPORTED")
    if descriptor.validation_status is not ValidationStatus.APPROVED:
        reasons.append("ALGORITHM_NOT_APPROVED")

    return CapabilityDecision(
        metric_id=descriptor.metric_id,
        status=(
            CapabilityStatus.UNSUPPORTED if reasons else CapabilityStatus.SUPPORTED
        ),
        internal_reason_codes=tuple(reasons),
    )
