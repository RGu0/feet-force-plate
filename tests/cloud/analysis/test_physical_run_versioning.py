from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from cloud.analysis.physical_runs import (
    InMemoryPhysicalAnalysisRepository,
    PhysicalAnalysisRun,
    PhysicalAnalysisRunKey,
    PhysicalRunStatus,
)


def make_key(**overrides: object) -> PhysicalAnalysisRunKey:
    values: dict[str, object] = {
        "tenant_id": "tenant-a",
        "session_id": "session-a",
        "input_manifest_sha256": "a" * 64,
        "hardware_adapter_version": "adapter/1",
        "input_schema_version": "physical-pressure-session/1.0",
        "measurement_conformance_version": "measurement/1",
        "calibration_profile_version": "calibration/1",
        "uncertainty_profile_version": "uncertainty/1",
        "input_validation_status": "VALIDATED",
        "test_protocol_version": "static-balance/1",
        "protocol_context_sha256": "e" * 64,
        "feature_pipeline_version": "static-balance-feature-pipeline/1.0",
        "feature_parameters_sha256": "b" * 64,
        "rule_set_version": "fall-screen-rule-set/1.0",
        "reference_population_id": "reference-60-plus-v1",
        "reference_artifact_sha256": "c" * 64,
        "questionnaire_snapshot_sha256": "d" * 64,
        "result_schema_version": "screening-result/1.0",
    }
    values.update(overrides)
    return PhysicalAnalysisRunKey(**values)


def make_run(key: PhysicalAnalysisRunKey) -> PhysicalAnalysisRun:
    return PhysicalAnalysisRun(
        analysis_run_id="run-1",
        key=key,
        source_event_id="event-1",
        correlation_id="corr-1",
        status=PhysicalRunStatus.RUNNING,
        feature_set=None,
        public_result=None,
        private_trace=(),
        error_code=None,
        started_at=datetime.now(UTC),
        completed_at=None,
    )


def test_run_key_hash_covers_every_versioned_identity_field() -> None:
    baseline = make_key()
    changed = make_key(feature_pipeline_version="static-balance-feature-pipeline/2.0")

    assert len(baseline.identity_sha256) == 64
    assert baseline.identity_sha256 != changed.identity_sha256
    assert baseline.identity_sha256 == make_key().identity_sha256


def test_same_complete_input_and_versions_are_idempotent() -> None:
    repository = InMemoryPhysicalAnalysisRepository()
    first = repository.reserve(make_run(make_key()))
    duplicate = repository.reserve(make_run(make_key()))

    assert duplicate.analysis_run_id == first.analysis_run_id
    assert repository.count() == 1


def test_changed_algorithm_version_creates_a_new_run() -> None:
    repository = InMemoryPhysicalAnalysisRepository()
    first = repository.reserve(make_run(make_key()))
    second = repository.reserve(
        replace(
            make_run(make_key(feature_pipeline_version="static-balance-feature-pipeline/2.0")),
            analysis_run_id="run-2",
        )
    )

    assert first.analysis_run_id != second.analysis_run_id
    assert repository.count() == 2


def test_terminal_runs_are_immutable() -> None:
    repository = InMemoryPhysicalAnalysisRepository()
    run = repository.reserve(make_run(make_key()))
    completed = replace(
        run,
        status=PhysicalRunStatus.SUCCEEDED,
        completed_at=datetime.now(UTC),
    )

    repository.save(completed)
    with pytest.raises(ValueError, match="terminal"):
        repository.save(
            replace(completed, status=PhysicalRunStatus.FAILED, error_code="E-ALG-500")
        )
