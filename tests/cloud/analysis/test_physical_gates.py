from __future__ import annotations

from cloud.analysis.feature_parameters import FeatureParameters
from cloud.analysis.features import extract_features
from cloud.analysis.models import CapabilityStatus, ValidationStatus
from cloud.analysis.physical_gates import (
    PhysicalCapabilityContext,
    PhysicalMetricDescriptor,
    evaluate_physical_capability,
    evaluate_risk_release_capability,
)
from cloud.analysis.physical_input import parse_physical_pressure_session

from test_physical_features import _session_payload


def descriptor(**overrides: object) -> PhysicalMetricDescriptor:
    values: dict[str, object] = {
        "metric_id": "cop_path_mm",
        "unit": "mm",
        "definition": "COP path",
        "input_schema_version": "physical-pressure-session/1.0",
        "measurement_conformance_version": "measurement-conformance/1",
        "calibration_profile_version": "calibration/1",
        "uncertainty_profile_version": "uncertainty/1",
        "protocol_version": "static-balance/1",
        "feature_pipeline_version": "static-balance-feature-pipeline/1.0",
        "feature_parameters_sha256": "a" * 64,
        "algorithm_version": "static-balance/1.0",
        "validation_status": ValidationStatus.APPROVED,
        "reference_artifact_sha256": "b" * 64,
        "approved_adapter_version": "adapter/1",
    }
    values.update(overrides)
    return PhysicalMetricDescriptor(**values)


def context(**overrides: object) -> PhysicalCapabilityContext:
    values: dict[str, object] = {
        "sample_rate_hz": 20.0,
        "valid_frame_ratio": 0.99,
        "completed_valid_duration_s": 20.0,
        "max_gap_nominal_intervals": 2.0,
        "reference_artifact_sha256": "b" * 64,
        "adapter_version": "adapter/1",
        "protocol_version": "static-balance/1",
        "rule_set_version": "static-balance/1.0",
    }
    values.update(overrides)
    return PhysicalCapabilityContext(**values)


def test_physical_gate_is_default_closed_without_approved_reference_or_quality() -> None:
    session = parse_physical_pressure_session(_session_payload())
    features = extract_features(
        session,
        FeatureParameters(version="physical-features/test", lowpass_cutoff_hz=0.0),
    )
    decision = evaluate_physical_capability(
        session=session,
        features=features,
        context=context(reference_artifact_sha256=None, sample_rate_hz=12.0),
        descriptor=descriptor(feature_parameters_sha256=features.parameters_sha256),
    )

    assert decision.status is CapabilityStatus.UNSUPPORTED
    assert "REFERENCE_ARTIFACT_NOT_APPROVED" in decision.internal_reason_codes
    assert "SAMPLE_RATE_TOO_LOW" in decision.internal_reason_codes


def test_approved_physical_metric_requires_no_device_shape_assumption() -> None:
    session = parse_physical_pressure_session(_session_payload())
    features = extract_features(
        session,
        FeatureParameters(version="physical-features/test", lowpass_cutoff_hz=0.0),
    )
    decision = evaluate_physical_capability(
        session=session,
        features=features,
        context=context(),
        descriptor=descriptor(feature_parameters_sha256=features.parameters_sha256),
    )

    assert decision.status is CapabilityStatus.SUPPORTED
    assert decision.internal_reason_codes == ()


def test_release_gate_rejects_feature_protocol_and_rule_version_mismatches() -> None:
    session = parse_physical_pressure_session(_session_payload())
    features = extract_features(
        session,
        FeatureParameters(version="physical-features/test", lowpass_cutoff_hz=0.0),
    )
    decision = evaluate_physical_capability(
        session=session,
        features=features,
        context=context(protocol_version="static-balance/2", rule_set_version="rules/2"),
        descriptor=descriptor(
            feature_parameters_sha256="a" * 64,
            calibration_profile_version="calibration/2",
        ),
    )

    assert decision.status is CapabilityStatus.UNSUPPORTED
    assert "FEATURE_PARAMETERS_MISMATCH" in decision.internal_reason_codes
    assert "PROTOCOL_VERSION_MISMATCH" in decision.internal_reason_codes
    assert "RULE_SET_VERSION_MISMATCH" in decision.internal_reason_codes
    assert "CALIBRATION_PROFILE_MISMATCH" in decision.internal_reason_codes


def test_risk_release_requires_the_ellipse_metric_bundle() -> None:
    session = parse_physical_pressure_session(_session_payload())
    features = extract_features(
        session,
        FeatureParameters(version="physical-features/test", lowpass_cutoff_hz=0.0),
    )
    decision = evaluate_risk_release_capability(
        session=session,
        features=features,
        context=context(),
        descriptor=descriptor(
            metric_id="cop_path_mm",
            unit="mm",
            feature_parameters_sha256=features.parameters_sha256,
        ),
    )

    assert decision.status is CapabilityStatus.UNSUPPORTED
    assert "RISK_RELEASE_METRIC_BUNDLE_MISMATCH" in decision.internal_reason_codes


def test_dynamic_gait_metric_is_not_in_v1_whitelist() -> None:
    session = parse_physical_pressure_session(_session_payload())
    features = extract_features(
        session,
        FeatureParameters(version="physical-features/test", lowpass_cutoff_hz=0.0),
    )
    decision = evaluate_physical_capability(
        session=session,
        features=features,
        context=context(),
        descriptor=descriptor(metric_id="stride_frequency_hz", unit="Hz"),
    )

    assert decision.status is CapabilityStatus.UNSUPPORTED
    assert "METRIC_NOT_IN_V1_WHITELIST" in decision.internal_reason_codes
