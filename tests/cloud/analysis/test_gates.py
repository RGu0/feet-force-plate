import unittest

from cloud.analysis.gates import evaluate_capability
from cloud.analysis.models import (
    AlgorithmDescriptor,
    CalibrationLevel,
    CapabilityStatus,
    SessionContext,
    ValidationStatus,
)


def make_context(**overrides: object) -> SessionContext:
    values: dict[str, object] = {
        "tenant_id": "tenant-a",
        "session_id": "session-a",
        "manifest_sha256": "a" * 64,
        "device_model": "DO-P4864",
        "actual_sample_rate_hz": 12.0,
        "calibration_level": CalibrationLevel.FORCE,
        "calibration_version": "calibration/1",
        "duration_seconds": 30.0,
        "validity_status": "VALID",
        "manifest_status": "VERIFIED",
        "cloud_quality_status": "PASS",
        "quality_flags": frozenset(),
        "test_protocol_id": "standard-screening",
        "profile_fields": frozenset({"height_cm"}),
    }
    values.update(overrides)
    return SessionContext(**values)


def make_descriptor(**overrides: object) -> AlgorithmDescriptor:
    values: dict[str, object] = {
        "algorithm_id": "relative-load-balance",
        "algorithm_version": "1.0.0",
        "metric_id": "relative_load_balance",
        "metric_definition_version": "1.0.0",
        "definition": "左右区域相对载荷差异",
        "unit": "%",
        "input_schema_version": "features/1",
        "output_schema_version": "metric/1",
        "required_sample_rate_hz": 10.0,
        "required_calibration_level": CalibrationLevel.RELATIVE,
        "required_duration_seconds": 20.0,
        "required_test_protocols": frozenset({"standard-screening"}),
        "required_profile_fields": frozenset(),
        "supported_device_models": frozenset({"DO-P4864"}),
        "blocked_quality_flags": frozenset(
            {"ABNORMAL_GAIT", "PAUSE_DETECTED", "INCOMPLETE_CYCLE"}
        ),
        "validation_status": ValidationStatus.APPROVED,
    }
    values.update(overrides)
    return AlgorithmDescriptor(**values)


class CapabilityGateTests(unittest.TestCase):
    def assertUnsupported(
        self,
        context: SessionContext,
        descriptor: AlgorithmDescriptor,
        expected_reason: str,
    ) -> None:
        decision = evaluate_capability(context, descriptor)
        self.assertEqual(decision.status, CapabilityStatus.UNSUPPORTED)
        self.assertIn(expected_reason, decision.internal_reason_codes)

    def test_supports_only_a_valid_session_meeting_every_requirement(self) -> None:
        decision = evaluate_capability(make_context(), make_descriptor())

        self.assertEqual(decision.status, CapabilityStatus.SUPPORTED)
        self.assertEqual(decision.internal_reason_codes, ())

    def test_rejects_invalid_session(self) -> None:
        self.assertUnsupported(
            make_context(validity_status="INVALID"),
            make_descriptor(),
            "SESSION_NOT_VALID",
        )

    def test_rejects_unverified_manifest(self) -> None:
        self.assertUnsupported(
            make_context(manifest_status="PENDING"),
            make_descriptor(),
            "MANIFEST_NOT_VERIFIED",
        )

    def test_rejects_low_sample_rate(self) -> None:
        self.assertUnsupported(
            make_context(actual_sample_rate_hz=9.99),
            make_descriptor(),
            "SAMPLE_RATE_TOO_LOW",
        )

    def test_hides_a_100_hz_metric_on_the_approximately_12_hz_device(self) -> None:
        self.assertUnsupported(
            make_context(actual_sample_rate_hz=12.0),
            make_descriptor(required_sample_rate_hz=100.0),
            "SAMPLE_RATE_TOO_LOW",
        )

    def test_rejects_insufficient_calibration(self) -> None:
        self.assertUnsupported(
            make_context(calibration_level=CalibrationLevel.NONE),
            make_descriptor(),
            "CALIBRATION_INSUFFICIENT",
        )

    def test_rejects_short_duration(self) -> None:
        self.assertUnsupported(
            make_context(duration_seconds=19.99),
            make_descriptor(),
            "DURATION_TOO_SHORT",
        )

    def test_rejects_wrong_protocol(self) -> None:
        self.assertUnsupported(
            make_context(test_protocol_id="dynamic-gait"),
            make_descriptor(),
            "PROTOCOL_UNSUPPORTED",
        )

    def test_rejects_missing_profile_fields(self) -> None:
        self.assertUnsupported(
            make_context(profile_fields=frozenset()),
            make_descriptor(required_profile_fields=frozenset({"height_cm"})),
            "PROFILE_FIELDS_MISSING",
        )

    def test_rejects_unsupported_device(self) -> None:
        self.assertUnsupported(
            make_context(device_model="OTHER"),
            make_descriptor(),
            "DEVICE_UNSUPPORTED",
        )

    def test_rejects_unapproved_algorithm(self) -> None:
        self.assertUnsupported(
            make_context(),
            make_descriptor(validation_status=ValidationStatus.DRAFT),
            "ALGORITHM_NOT_APPROVED",
        )

    def test_rejects_failed_cloud_quality(self) -> None:
        self.assertUnsupported(
            make_context(cloud_quality_status="FAIL"),
            make_descriptor(),
            "CLOUD_QUALITY_FAILED",
        )

    def test_rejects_blocking_quality_flags(self) -> None:
        decision = evaluate_capability(
            make_context(quality_flags=frozenset({"PAUSE_DETECTED"})),
            make_descriptor(),
        )

        self.assertEqual(decision.status, CapabilityStatus.UNSUPPORTED)
        self.assertIn("QUALITY_FLAG_BLOCKED:PAUSE_DETECTED", decision.internal_reason_codes)

    def test_metric_descriptor_requires_customer_facing_definition_and_unit(self) -> None:
        with self.assertRaisesRegex(ValueError, "definition"):
            make_descriptor(definition="")
        with self.assertRaisesRegex(ValueError, "unit"):
            make_descriptor(unit="")


if __name__ == "__main__":
    unittest.main()
