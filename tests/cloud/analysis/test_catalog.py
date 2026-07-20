import unittest

from cloud.analysis.catalog import MetricCatalog, default_metric_catalog
from cloud.analysis.gates import evaluate_capability
from cloud.analysis.models import (
    AlgorithmDescriptor,
    CalibrationLevel,
    CapabilityStatus,
    SessionContext,
    ValidationStatus,
)


def descriptor(metric_id: str, version: str = "1.0.0") -> AlgorithmDescriptor:
    return AlgorithmDescriptor(
        algorithm_id=f"algorithm-{metric_id}",
        algorithm_version=version,
        metric_id=metric_id,
        metric_definition_version=version,
        definition=f"Definition for {metric_id}",
        unit="%",
        input_schema_version="features/1",
        output_schema_version="metric/1",
        required_sample_rate_hz=10.0,
        required_calibration_level=CalibrationLevel.RELATIVE,
        required_duration_seconds=20.0,
        required_test_protocols=frozenset({"standard-screening"}),
        required_profile_fields=frozenset(),
        supported_device_models=frozenset({"DO-P4864"}),
        blocked_quality_flags=frozenset(),
        validation_status=ValidationStatus.DRAFT,
    )


class MetricCatalogTests(unittest.TestCase):
    def test_catalog_versions_each_metric_definition(self) -> None:
        catalog = MetricCatalog((descriptor("left_right_balance"),))

        registered = catalog.get("left_right_balance", "1.0.0")

        self.assertEqual(registered.definition, "Definition for left_right_balance")
        self.assertEqual(registered.unit, "%")
        self.assertEqual(registered.algorithm_version, "1.0.0")
        self.assertEqual(registered.validation_status, ValidationStatus.DRAFT)

    def test_catalog_rejects_duplicate_metric_definition_versions(self) -> None:
        with self.assertRaisesRegex(ValueError, "duplicate metric definition"):
            MetricCatalog((descriptor("left_right_balance"), descriptor("left_right_balance")))

    def test_default_catalog_keeps_unvalidated_metrics_closed(self) -> None:
        catalog = default_metric_catalog()

        self.assertEqual(
            {item.metric_id for item in catalog.all()},
            {
                "relative_total_load",
                "left_right_load_balance",
                "anterior_posterior_load_balance",
                "cop_path_length",
                "gait_temporal_spatial",
            },
        )
        self.assertTrue(
            all(item.validation_status is ValidationStatus.DRAFT for item in catalog.all())
        )

    def test_default_gait_metric_is_both_unapproved_and_above_12_hz_capability(self) -> None:
        gait = default_metric_catalog().get("gait_temporal_spatial", "1.0.0")
        context = SessionContext(
            tenant_id="tenant-a",
            session_id="session-a",
            manifest_sha256="a" * 64,
            device_model="DO-P4864",
            actual_sample_rate_hz=12.0,
            calibration_level=CalibrationLevel.FORCE,
            calibration_version="calibration/1",
            duration_seconds=30.0,
            validity_status="VALID",
            manifest_status="VERIFIED",
            cloud_quality_status="PASS",
            quality_flags=frozenset(),
            test_protocol_id="standard-screening",
            profile_fields=frozenset(),
        )

        decision = evaluate_capability(context, gait)

        self.assertEqual(decision.status, CapabilityStatus.UNSUPPORTED)
        self.assertIn("SAMPLE_RATE_TOO_LOW", decision.internal_reason_codes)
        self.assertIn("ALGORITHM_NOT_APPROVED", decision.internal_reason_codes)


if __name__ == "__main__":
    unittest.main()
