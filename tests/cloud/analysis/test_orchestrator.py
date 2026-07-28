import unittest
from dataclasses import asdict

from cloud.analysis.features import FeaturePipeline
from cloud.analysis.models import (
    AlgorithmDescriptor,
    AnalysisRunStatus,
    CalibrationLevel,
    QualityAssessment,
    RawSession,
    SessionContext,
    SessionIngestedEvent,
    ValidationStatus,
)
from cloud.analysis.orchestrator import (
    AnalysisOrchestrator,
    InMemoryAnalysisRepository,
    InMemoryEventPublisher,
    RegisteredMetric,
)


def frame() -> tuple[int, ...]:
    return tuple([1] * (48 * 64))


def context(**overrides: object) -> SessionContext:
    values: dict[str, object] = {
        "tenant_id": "tenant-a",
        "session_id": "session-a",
        "manifest_sha256": "a" * 64,
        "device_model": "DO-P4864",
        "actual_sample_rate_hz": 12.0,
        "calibration_level": CalibrationLevel.RELATIVE,
        "calibration_version": "calibration/1",
        "duration_seconds": 30.0,
        "validity_status": "VALID",
        "manifest_status": "VERIFIED",
        "cloud_quality_status": "PASS",
        "quality_flags": frozenset(),
        "test_protocol_id": "standard-screening",
        "profile_fields": frozenset(),
    }
    values.update(overrides)
    return SessionContext(**values)


def event(**overrides: object) -> SessionIngestedEvent:
    values: dict[str, object] = {
        "event_id": "event-a",
        "event_type": "session.ingested.v1",
        "tenant_id": "tenant-a",
        "session_id": "session-a",
        "manifest_sha256": "a" * 64,
        "payload_schema_version": "raw-segment/1",
        "protocol_profile_version": "do-p4864/1",
        "calibration_version": "calibration/1",
        "correlation_id": "correlation-a",
    }
    values.update(overrides)
    return SessionIngestedEvent(**values)


def metric(**overrides: object) -> AlgorithmDescriptor:
    values: dict[str, object] = {
        "algorithm_id": "total-relative-load",
        "algorithm_version": "1.0.0",
        "metric_id": "relative_total_load",
        "metric_definition_version": "1.0.0",
        "definition": "平均相对总载荷",
        "unit": "relative_count",
        "input_schema_version": "features/1",
        "output_schema_version": "metric/1",
        "required_sample_rate_hz": 10.0,
        "required_calibration_level": CalibrationLevel.RELATIVE,
        "required_duration_seconds": 20.0,
        "required_test_protocols": frozenset({"standard-screening"}),
        "required_profile_fields": frozenset(),
        "supported_device_models": frozenset({"DO-P4864"}),
        "blocked_quality_flags": frozenset(),
        "validation_status": ValidationStatus.APPROVED,
    }
    values.update(overrides)
    return AlgorithmDescriptor(**values)


class Loader:
    def __init__(self, raw: RawSession | None = None, error: Exception | None = None) -> None:
        self.raw = raw or RawSession(context=context(), frames=(frame(),))
        self.error = error
        self.calls = 0

    def load(self, ingested: SessionIngestedEvent) -> RawSession:
        self.calls += 1
        if self.error:
            raise self.error
        return self.raw


class Assessor:
    def __init__(self, assessment: QualityAssessment | None = None) -> None:
        self.assessment = assessment or QualityAssessment("PASS", frozenset())

    def assess(self, raw: RawSession) -> QualityAssessment:
        return self.assessment


def orchestrator(
    *,
    repository: InMemoryAnalysisRepository | None = None,
    publisher: InMemoryEventPublisher | None = None,
    loader: Loader | None = None,
    algorithm_set_version: str = "algorithms/1",
    descriptor: AlgorithmDescriptor | None = None,
) -> AnalysisOrchestrator:
    registered = RegisteredMetric(
        descriptor=descriptor or metric(),
        compute=lambda features: sum(features.total_load_by_frame)
        / len(features.total_load_by_frame),
    )
    return AnalysisOrchestrator(
        loader=loader or Loader(),
        quality_assessor=Assessor(),
        feature_pipeline=FeaturePipeline("features/1"),
        registered_metrics=(registered,),
        repository=repository or InMemoryAnalysisRepository(),
        publisher=publisher or InMemoryEventPublisher(),
        algorithm_set_version=algorithm_set_version,
        model_set_version="models/none",
        report_schema_version="report-document/1",
        parameters={"contact_threshold": 0},
    )


class AnalysisOrchestratorTests(unittest.TestCase):
    def test_only_accepts_the_approved_complete_session_event(self) -> None:
        repository = InMemoryAnalysisRepository()
        service = orchestrator(repository=repository)

        with self.assertRaisesRegex(ValueError, "session.ingested.v1"):
            service.handle(event(event_type="session.uploaded.v1"))

        self.assertEqual(repository.count(), 0)

    def test_legacy_raw_array_pipeline_rejects_standard_physical_sessions(self) -> None:
        repository = InMemoryAnalysisRepository()
        service = orchestrator(repository=repository)

        with self.assertRaisesRegex(ValueError, "PhysicalAnalysisOrchestrator"):
            service.handle(event(payload_schema_version="physical-pressure-session/1.1"))

        self.assertEqual(repository.count(), 0)

    def test_duplicate_delivery_returns_the_same_persisted_run(self) -> None:
        repository = InMemoryAnalysisRepository()
        publisher = InMemoryEventPublisher()
        loader = Loader()
        service = orchestrator(repository=repository, publisher=publisher, loader=loader)

        first = service.handle(event())
        second = service.handle(event(event_id="event-redelivery"))

        self.assertEqual(first, second)
        self.assertEqual(first.status, AnalysisRunStatus.SUCCEEDED)
        self.assertEqual(repository.count(), 1)
        self.assertEqual(loader.calls, 1)
        self.assertEqual(
            [published.event_type for published in publisher.events],
            ["analysis.started.v1", "analysis.completed.v1"],
        )

    def test_algorithm_upgrade_creates_a_new_run_without_overwriting_history(self) -> None:
        repository = InMemoryAnalysisRepository()
        first = orchestrator(repository=repository, algorithm_set_version="algorithms/1")
        second = orchestrator(repository=repository, algorithm_set_version="algorithms/2")

        run_v1 = first.handle(event())
        run_v2 = second.handle(event(event_id="event-recompute"))

        self.assertNotEqual(run_v1.analysis_run_id, run_v2.analysis_run_id)
        self.assertEqual(repository.count(), 2)
        self.assertEqual(run_v1.key.algorithm_set_version, "algorithms/1")
        self.assertEqual(run_v2.key.algorithm_set_version, "algorithms/2")

    def test_persists_all_input_and_runtime_versions_for_traceability(self) -> None:
        run = orchestrator().handle(event())

        self.assertEqual(run.key.input_manifest_sha256, "a" * 64)
        self.assertEqual(run.key.payload_schema_version, "raw-segment/1")
        self.assertEqual(run.key.protocol_profile_version, "do-p4864/1")
        self.assertEqual(run.key.calibration_version, "calibration/1")
        self.assertEqual(run.key.pipeline_version, "features/1")
        self.assertEqual(run.key.algorithm_set_version, "algorithms/1")
        self.assertEqual(run.key.model_set_version, "models/none")
        self.assertEqual(run.report_schema_version, "report-document/1")
        self.assertEqual(run.feature_set.manifest_sha256, "a" * 64)

    def test_unsupported_metric_does_not_publish_completed_event(self) -> None:
        publisher = InMemoryEventPublisher()
        service = orchestrator(
            publisher=publisher,
            descriptor=metric(required_sample_rate_hz=100.0),
        )

        run = service.handle(event())

        self.assertEqual(run.status, AnalysisRunStatus.UNSUPPORTED)
        self.assertEqual(run.metric_results, ())
        self.assertIn(
            ("relative_total_load", ("SAMPLE_RATE_TOO_LOW",)),
            run.capability_reasons,
        )
        self.assertEqual(
            [published.event_type for published in publisher.events],
            ["analysis.started.v1"],
        )

    def test_failures_persist_only_safe_error_evidence(self) -> None:
        repository = InMemoryAnalysisRepository()
        publisher = InMemoryEventPublisher()
        loader = Loader(error=RuntimeError("subject_name=Alice token=secret"))
        service = orchestrator(
            repository=repository,
            publisher=publisher,
            loader=loader,
        )

        run = service.handle(event())

        self.assertEqual(run.status, AnalysisRunStatus.FAILED)
        self.assertEqual(run.error_code, "E-ALG-500")
        self.assertNotIn("Alice", repr(run))
        self.assertNotIn("secret", repr(run))
        self.assertNotIn("Alice", repr(publisher.events))
        self.assertNotIn("secret", repr(publisher.events))
        self.assertEqual(
            [published.event_type for published in publisher.events],
            ["analysis.started.v1", "analysis.failed.v1"],
        )

    def test_event_contract_cannot_accept_direct_identity_fields(self) -> None:
        with self.assertRaises(TypeError):
            SessionIngestedEvent(
                **asdict(event()),
                subject_name="Alice",
            )

    def test_quality_assessment_is_applied_before_metric_gates(self) -> None:
        service = orchestrator()
        service.quality_assessor = Assessor(QualityAssessment("FAIL", frozenset()))

        run = service.handle(event())

        self.assertEqual(run.status, AnalysisRunStatus.UNSUPPORTED)
        self.assertIn(
            ("relative_total_load", ("CLOUD_QUALITY_FAILED",)),
            run.capability_reasons,
        )


if __name__ == "__main__":
    unittest.main()
