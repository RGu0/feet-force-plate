from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from cloud.analysis.feature_parameters import FeatureParameters
from cloud.analysis.physical_input import parse_physical_pressure_session
from cloud.analysis.physical_orchestrator import (
    CompleteSessionEvent,
    InMemoryPhysicalSessionLoader,
    PhysicalAnalysisOrchestrator,
)
from cloud.analysis.physical_runs import (
    InMemoryPhysicalAnalysisRepository,
    PhysicalRunStatus,
)
from cloud.analysis.features import extract_features

from test_physical_features import _session_payload


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
        "uncertainty_profile_version": "uncertainty/1",
        "test_protocol_version": "static-balance/1",
        "feature_pipeline_version": "static-balance-feature-pipeline/1.0",
        "rule_set_version": "fall-screen-rule-set/1.0",
        "reference_population_id": "reference-60-plus-v1",
        "reference_artifact_sha256": "b" * 64,
        "questionnaire_snapshot_sha256": "c" * 64,
        "result_schema_version": "screening-result/1.0",
        "correlation_id": "corr-physical-1",
    }
    values.update(overrides)
    return CompleteSessionEvent(**values)


def make_orchestrator() -> tuple[PhysicalAnalysisOrchestrator, InMemoryPhysicalAnalysisRepository]:
    repository = InMemoryPhysicalAnalysisRepository()
    loader = InMemoryPhysicalSessionLoader(
        parse_physical_pressure_session(_session_payload())
    )
    orchestrator = PhysicalAnalysisOrchestrator(
        loader=loader,
        repository=repository,
        parameters=FeatureParameters(
            version="physical-features/test",
            despike_window_samples=1,
            lowpass_cutoff_hz=0.0,
        ),
    )
    return orchestrator, repository


def test_only_ingested_complete_triggers_feature_reconstruction() -> None:
    orchestrator, repository = make_orchestrator()

    with pytest.raises(ValueError, match="INGESTED_COMPLETE"):
        orchestrator.handle(make_event(event_type="session.ingested.v1"))

    assert repository.count() == 0


def test_complete_event_loads_standard_session_and_persists_features() -> None:
    orchestrator, repository = make_orchestrator()

    run = orchestrator.handle(make_event())

    assert run.status is PhysicalRunStatus.FEATURES_READY
    assert run.feature_set is not None
    assert run.public_result is None
    assert run.completed_at is None
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
