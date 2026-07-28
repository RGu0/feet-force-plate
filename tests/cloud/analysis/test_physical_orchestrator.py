from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from cloud.analysis.feature_parameters import FeatureParameters
from cloud.analysis.models import ValidationStatus
from cloud.analysis.physical_gates import PhysicalMetricDescriptor
from cloud.analysis.physical_input import PhysicalInputValidationStatus, parse_physical_pressure_session
from cloud.analysis.physical_orchestrator import (
    CompleteSessionEvent,
    InMemoryPhysicalSessionLoader,
    InMemoryQuestionnaireLoader,
    PhysicalAnalysisOrchestrator,
)
from cloud.analysis.physical_runs import (
    InMemoryPhysicalAnalysisRepository,
    PhysicalRunStatus,
)
from cloud.analysis.features import extract_features
from cloud.analysis.risk_rules import (
    QuestionnaireSnapshot,
    RiskTier,
    questionnaire_snapshot_sha256,
)
from cloud.analysis.protocol_context import protocol_context_sha256

from test_physical_features import _session_payload
from test_physical_input import valid_protocol_context


def make_event(**overrides: object) -> CompleteSessionEvent:
    values: dict[str, object] = {
        "event_id": "event-physical-1",
        "event_type": "INGESTED_COMPLETE",
        "tenant_id": "tenant-a",
        "session_id": "session-physical-1",
        "manifest_sha256": "a" * 64,
        "hardware_adapter_version": "adapter/1",
        "input_schema_version": "physical-pressure-session/1.0",
        "measurement_conformance_version": "measurement-conformance/1",
        "calibration_profile_version": "calibration/1",
        "uncertainty_profile_version": "uncertainty/1",
        "input_validation_status": PhysicalInputValidationStatus.VALIDATED,
        "test_protocol_version": "static-balance/1",
        "protocol_context": valid_protocol_context(),
        "protocol_context_sha256": protocol_context_sha256(valid_protocol_context()),
        "feature_pipeline_version": "static-balance-feature-pipeline/1.0",
        "rule_set_version": "fall-screen-rule-set/1.0",
        "reference_population_id": "reference-60-plus-v1",
        "reference_artifact_sha256": "b" * 64,
        "questionnaire_snapshot_sha256": questionnaire_snapshot_sha256(
            QuestionnaireSnapshot(
                age_years=72,
                recent_fall_12m=False,
                recurrent_dizziness=False,
                medication_tags=frozenset(),
            )
        ),
        "result_schema_version": "screening-result/1.0",
        "correlation_id": "corr-physical-1",
    }
    values.update(overrides)
    return CompleteSessionEvent(**values)


def release_descriptor(**overrides: object) -> PhysicalMetricDescriptor:
    values: dict[str, object] = {
        "metric_id": "ellipse_area_95_mm2",
        "unit": "mm2",
        "definition": "COP 95 percent ellipse area",
        "input_schema_version": "physical-pressure-session/1.0",
        "measurement_conformance_version": "measurement-conformance/1",
        "calibration_profile_version": "calibration/1",
        "uncertainty_profile_version": "uncertainty/1",
        "protocol_version": "static-balance/1",
        "feature_pipeline_version": "static-balance-feature-pipeline/1.0",
        "feature_parameters_sha256": "configured-by-make-orchestrator",
        "algorithm_version": "fall-screen-rule-set/1.0",
        "validation_status": ValidationStatus.APPROVED,
        "reference_artifact_sha256": "b" * 64,
        "approved_adapter_version": "adapter/1",
    }
    values.update(overrides)
    return PhysicalMetricDescriptor(**values)


def make_orchestrator(
    *,
    sample_rate_hz: float = 20.0,
) -> tuple[PhysicalAnalysisOrchestrator, InMemoryPhysicalAnalysisRepository]:
    repository = InMemoryPhysicalAnalysisRepository()
    parameters = FeatureParameters(
        version="physical-features/test",
        despike_window_samples=1,
        lowpass_cutoff_hz=0.0,
    )
    session = parse_physical_pressure_session(_session_payload(sample_rate_hz=sample_rate_hz))
    loader = InMemoryPhysicalSessionLoader(
        session
    )
    orchestrator = PhysicalAnalysisOrchestrator(
        loader=loader,
        repository=repository,
        parameters=parameters,
        release_descriptor=release_descriptor(
            feature_parameters_sha256=extract_features(
                session, valid_protocol_context(), parameters
            ).parameters_sha256
        ),
        questionnaire_loader=InMemoryQuestionnaireLoader(
            QuestionnaireSnapshot(
                age_years=72,
                recent_fall_12m=False,
                recurrent_dizziness=False,
                medication_tags=frozenset(),
            )
        ),
    )
    return orchestrator, repository


def test_only_ingested_complete_triggers_feature_reconstruction() -> None:
    orchestrator, repository = make_orchestrator()

    with pytest.raises(ValueError, match="INGESTED_COMPLETE"):
        orchestrator.handle(make_event(event_type="session.ingested.v1"))

    assert repository.count() == 0


def test_complete_event_runs_gate_features_and_risk_before_public_result() -> None:
    orchestrator, repository = make_orchestrator()

    run = orchestrator.handle(make_event())

    assert run.status is PhysicalRunStatus.SUCCEEDED
    assert run.feature_set is not None
    assert run.public_result is not None
    assert run.public_result.risk_tier is RiskTier.MEDIUM
    assert run.completed_at is not None
    assert repository.count() == 1


def test_duplicate_complete_event_is_idempotent() -> None:
    orchestrator, repository = make_orchestrator()
    event = make_event()

    first = orchestrator.handle(event)
    second = orchestrator.handle(event)

    assert first.analysis_run_id == second.analysis_run_id
    assert repository.count() == 1


def test_loader_failure_persists_internal_failure_without_public_result() -> None:
    orchestrator, repository = make_orchestrator()
    orchestrator.loader = InMemoryPhysicalSessionLoader(error=RuntimeError("private detail"))

    run = orchestrator.handle(make_event())

    assert run.status is PhysicalRunStatus.FAILED
    assert run.error_code == "E-ALG-PHYSICAL-INPUT"
    assert run.public_result is None
    assert "private detail" not in str(run.private_trace)


def test_capability_failure_never_emits_a_public_risk_result() -> None:
    orchestrator, repository = make_orchestrator(sample_rate_hz=1.0)

    run = orchestrator.handle(make_event())

    assert run.status is PhysicalRunStatus.UNSUPPORTED
    assert run.public_result is None
    assert run.error_code == "E-ALG-CAPABILITY"
    assert repository.count() == 1


def test_questionnaire_hash_mismatch_never_emits_a_public_risk_result() -> None:
    orchestrator, repository = make_orchestrator()

    run = orchestrator.handle(make_event(questionnaire_snapshot_sha256="d" * 64))

    assert run.status is PhysicalRunStatus.FAILED
    assert run.public_result is None
    assert run.error_code == "E-ALG-QUESTIONNAIRE"
    assert repository.count() == 1


def test_event_feature_pipeline_version_mismatch_never_emits_a_public_result() -> None:
    orchestrator, repository = make_orchestrator()

    run = orchestrator.handle(
        make_event(feature_pipeline_version="static-balance-feature-pipeline/2.0")
    )

    assert run.status is PhysicalRunStatus.FAILED
    assert run.public_result is None
    assert run.error_code == "E-ALG-PHYSICAL-INPUT"
    assert repository.count() == 1


def test_protocol_context_hash_mismatch_never_emits_a_public_result() -> None:
    orchestrator, repository = make_orchestrator()
    run = orchestrator.handle(make_event(protocol_context_sha256="e" * 64))
    assert run.status is PhysicalRunStatus.FAILED
    assert run.public_result is None
    assert run.error_code == "E-ALG-PROTOCOL-CONTEXT"
    assert repository.count() == 1
