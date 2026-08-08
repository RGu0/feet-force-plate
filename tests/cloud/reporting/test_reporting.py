import hashlib
import json
import unittest
from dataclasses import replace
from datetime import UTC, datetime

from cloud.analysis.models import (
    AnalysisRun,
    AnalysisRunKey,
    AnalysisRunStatus,
    FeatureSet,
    MetricResult,
    ValidationStatus,
)
from cloud.reporting.builder import CloudReportBuilder
from cloud.reporting.models import ReportContext, ReportKind
from cloud.reporting.pdf import MinimalPdfRenderer
from cloud.reporting.service import (
    CloudReportService,
    InMemoryArtifactStore,
    InMemoryReportEventPublisher,
    InMemoryReportRepository,
)


def feature_set() -> FeatureSet:
    return FeatureSet(
        tenant_id="tenant-a",
        session_id="session-a",
        manifest_sha256="a" * 64,
        calibration_version="calibration/1",
        pipeline_version="features/1",
        parameters_sha256="b" * 64,
        cache_key="c" * 64,
        total_load_by_frame=(100.0, 120.0),
        left_load_by_frame=(50.0, 55.0),
        right_load_by_frame=(50.0, 65.0),
        anterior_load_by_frame=(40.0, 48.0),
        posterior_load_by_frame=(60.0, 72.0),
        contact_area_by_frame=(50, 52),
        cop_xy_by_frame=((31.5, 23.5), (32.0, 23.0)),
        actual_sample_rate_hz=12.0,
        mean_sensor_load=(),
    )


def metric_result(**overrides: object) -> MetricResult:
    values: dict[str, object] = {
        "metric_id": "left_right_load_balance",
        "metric_definition_version": "1.0.0",
        "definition": "左右区域相对载荷占比差异",
        "unit": "%",
        "algorithm_id": "cloud-left-right-load-balance",
        "algorithm_version": "1.0.0",
        "value_numeric": 4.2,
        "validation_status": ValidationStatus.APPROVED,
        "feature_cache_key": "c" * 64,
    }
    values.update(overrides)
    return MetricResult(**values)


def analysis_run(**overrides: object) -> AnalysisRun:
    key = AnalysisRunKey(
        tenant_id="tenant-a",
        session_id="session-a",
        pipeline_version="features/1",
        algorithm_set_version="algorithms/1",
        model_set_version="models/none",
        report_schema_version="report-document/1",
        calibration_version="calibration/1",
        payload_schema_version="raw-segment/1",
        protocol_profile_version="do-p4864/1",
        input_manifest_sha256="a" * 64,
        parameters_sha256="b" * 64,
    )
    values: dict[str, object] = {
        "analysis_run_id": "run-1",
        "key": key,
        "source_event_id": "event-1",
        "correlation_id": "correlation-1",
        "report_schema_version": "report-document/1",
        "status": AnalysisRunStatus.SUCCEEDED,
        "feature_set": feature_set(),
        "metric_results": (metric_result(),),
        "capability_reasons": (),
        "error_code": None,
        "started_at": datetime(2026, 7, 20, 8, 0, tzinfo=UTC),
        "completed_at": datetime(2026, 7, 20, 8, 1, tzinfo=UTC),
    }
    values.update(overrides)
    return AnalysisRun(**values)


def report_context() -> ReportContext:
    return ReportContext(
        masked_subject_id="**2781",
        institution_name="示例机构",
        site_name="主站点",
        test_protocol_name="静态筛查",
        tested_at=datetime(2026, 7, 20, 7, 30, tzinfo=UTC),
    )


def service() -> tuple[
    CloudReportService,
    InMemoryReportRepository,
    InMemoryArtifactStore,
    InMemoryReportEventPublisher,
]:
    repository = InMemoryReportRepository()
    repository.seed_basic(
        tenant_id="tenant-a",
        session_id="session-a",
        report_id="report-a",
        document_sha256="d" * 64,
        artifact_sha256="e" * 64,
    )
    artifacts = InMemoryArtifactStore()
    events = InMemoryReportEventPublisher()
    report_service = CloudReportService(
        repository=repository,
        artifact_store=artifacts,
        builder=CloudReportBuilder(),
        renderer=MinimalPdfRenderer(),
        publisher=events,
    )
    return report_service, repository, artifacts, events


class CloudReportingTests(unittest.TestCase):
    def test_cloud_version_reuses_basic_report_id_and_appends_version_two(self) -> None:
        report_service, repository, artifacts, events = service()

        published = report_service.publish(analysis_run(), report_context())
        report = repository.get_for_session("tenant-a", "session-a")

        self.assertIsNotNone(published)
        self.assertEqual(published.report_id, "report-a")
        self.assertEqual(published.version_number, 2)
        self.assertEqual(published.kind, ReportKind.CLOUD_COMPLETE)
        self.assertEqual([version.kind for version in report.versions], [ReportKind.BASIC, ReportKind.CLOUD_COMPLETE])
        self.assertEqual(report.latest_version, 2)
        self.assertEqual(artifacts.count(), 1)
        self.assertEqual([event.event_type for event in events.events], ["report.published.v1"])

    def test_duplicate_analysis_completion_is_idempotent(self) -> None:
        report_service, repository, artifacts, events = service()

        first = report_service.publish(analysis_run(), report_context())
        second = report_service.publish(analysis_run(), report_context())

        self.assertEqual(first, second)
        self.assertEqual(repository.get_for_session("tenant-a", "session-a").latest_version, 2)
        self.assertEqual(artifacts.count(), 1)
        self.assertEqual(len(events.events), 1)

    def test_recomputed_analysis_appends_version_without_overwriting_history(self) -> None:
        report_service, repository, _, _ = service()
        first = report_service.publish(analysis_run(), report_context())
        recomputed = replace(
            analysis_run(),
            analysis_run_id="run-2",
            key=replace(analysis_run().key, algorithm_set_version="algorithms/2"),
        )

        second = report_service.publish(recomputed, report_context())
        report = repository.get_for_session("tenant-a", "session-a")

        self.assertEqual(first.version_number, 2)
        self.assertEqual(second.version_number, 3)
        self.assertEqual([version.version_number for version in report.versions], [1, 2, 3])
        self.assertEqual(report.versions[1].source_analysis_run_id, "run-1")
        self.assertEqual(report.versions[2].source_analysis_run_id, "run-2")

    def test_failed_or_unsupported_analysis_cannot_publish_customer_report(self) -> None:
        for status in (AnalysisRunStatus.FAILED, AnalysisRunStatus.UNSUPPORTED):
            report_service, repository, artifacts, _ = service()
            run = replace(analysis_run(), status=status)

            with self.subTest(status=status):
                self.assertIsNone(report_service.publish(run, report_context()))
                self.assertEqual(repository.get_for_session("tenant-a", "session-a").latest_version, 1)
                self.assertEqual(artifacts.count(), 0)

    def test_only_approved_metric_results_enter_customer_document(self) -> None:
        report_service, _, _, _ = service()
        run = replace(
            analysis_run(),
            metric_results=(
                metric_result(),
                metric_result(
                    metric_id="draft_metric",
                    validation_status=ValidationStatus.DRAFT,
                ),
            ),
        )

        published = report_service.publish(run, report_context())

        self.assertEqual(
            [metric.metric_id for metric in published.document.core_metrics],
            ["left_right_load_balance"],
        )

    def test_public_document_has_fixed_order_and_no_internal_quality_or_debug_fields(self) -> None:
        report_service, _, artifacts, _ = service()

        published = report_service.publish(analysis_run(), report_context())
        public = published.document.to_public_dict()
        serialized = json.dumps(public, ensure_ascii=False)
        pdf = artifacts.get(published.artifact.object_key)

        self.assertEqual(
            list(public),
            [
                "identity",
                "screening_summary",
                "risk_prompts",
                "core_metrics",
                "professional_parameters_and_curves",
                "plain_language_guidance",
                "institution",
                "provenance",
            ],
        )
        for forbidden in (
            "internal_quality",
            "capability_reasons",
            "feature_cache_key",
            "manifest_sha256",
            "error_code",
            "stack_trace",
            "debug",
        ):
            self.assertNotIn(forbidden, serialized)
            self.assertNotIn(forbidden.encode(), pdf)
        self.assertNotIn("确诊", serialized)
        self.assertNotIn("治疗方案", serialized)
        self.assertIn("建议进一步评估", serialized)

    def test_pdf_artifact_is_hashed_and_uses_only_internal_object_path_ids(self) -> None:
        report_service, _, artifacts, _ = service()

        published = report_service.publish(analysis_run(), report_context())
        pdf = artifacts.get(published.artifact.object_key)

        self.assertTrue(pdf.startswith(b"%PDF-1.4"))
        self.assertEqual(hashlib.sha256(pdf).hexdigest(), published.artifact.sha256)
        self.assertEqual(len(pdf), published.artifact.size_bytes)
        self.assertEqual(
            published.artifact.object_key,
            (
                "tenants/tenant-a/reports/report-a/v2/"
                f"{published.artifact.sha256}.pdf"
            ),
        )

    def test_report_schema_has_no_public_link_qr_or_subject_account_delivery(self) -> None:
        report_service, _, _, _ = service()

        public = report_service.publish(analysis_run(), report_context()).document.to_public_dict()
        serialized = json.dumps(public, ensure_ascii=False).lower()

        for forbidden in ("public_url", "qr_code", "subject_account"):
            self.assertNotIn(forbidden, serialized)


if __name__ == "__main__":
    unittest.main()
