from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from typing import Protocol

from cloud.analysis.feature_parameters import FeatureParameters
from cloud.analysis.features import SessionFeatureSet, extract_features
from cloud.analysis.physical_input import (
    PhysicalPressureSession,
    validate_physical_pressure_session,
)
from cloud.analysis.physical_runs import (
    InMemoryPhysicalAnalysisRepository,
    PhysicalAnalysisRun,
    PhysicalAnalysisRunKey,
    PhysicalRunStatus,
)


@dataclass(frozen=True, slots=True)
class CompleteSessionEvent:
    event_id: str
    event_type: str
    tenant_id: str
    session_id: str
    manifest_sha256: str
    hardware_adapter_version: str
    input_schema_version: str
    measurement_conformance_version: str
    uncertainty_profile_version: str
    test_protocol_version: str
    feature_pipeline_version: str
    rule_set_version: str
    reference_population_id: str
    reference_artifact_sha256: str
    questionnaire_snapshot_sha256: str
    result_schema_version: str
    correlation_id: str


class PhysicalSessionLoader(Protocol):
    def load(self, event: CompleteSessionEvent) -> PhysicalPressureSession: ...


class InMemoryPhysicalSessionLoader:
    def __init__(
        self,
        session: PhysicalPressureSession | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.session = session
        self.error = error

    def load(self, event: CompleteSessionEvent) -> PhysicalPressureSession:
        if self.error is not None:
            raise self.error
        if self.session is None:
            raise ValueError("physical session is unavailable")
        return self.session


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class PhysicalAnalysisOrchestrator:
    """Rebuild and persist standard physical features after complete ingestion."""

    def __init__(
        self,
        *,
        loader: PhysicalSessionLoader,
        repository: InMemoryPhysicalAnalysisRepository,
        parameters: FeatureParameters,
    ) -> None:
        self.loader = loader
        self.repository = repository
        self.parameters = parameters

    def handle(self, event: CompleteSessionEvent) -> PhysicalAnalysisRun:
        if event.event_type != "INGESTED_COMPLETE":
            raise ValueError("analysis only accepts INGESTED_COMPLETE")
        key = PhysicalAnalysisRunKey(
            tenant_id=event.tenant_id,
            session_id=event.session_id,
            input_manifest_sha256=event.manifest_sha256,
            hardware_adapter_version=event.hardware_adapter_version,
            input_schema_version=event.input_schema_version,
            measurement_conformance_version=event.measurement_conformance_version,
            uncertainty_profile_version=event.uncertainty_profile_version,
            test_protocol_version=event.test_protocol_version,
            feature_pipeline_version=event.feature_pipeline_version,
            feature_parameters_sha256=_canonical_sha256(asdict(self.parameters)),
            rule_set_version=event.rule_set_version,
            reference_population_id=event.reference_population_id,
            reference_artifact_sha256=event.reference_artifact_sha256,
            questionnaire_snapshot_sha256=event.questionnaire_snapshot_sha256,
            result_schema_version=event.result_schema_version,
        )
        existing = self.repository.get(key)
        if existing is not None:
            return existing
        candidate = PhysicalAnalysisRun(
            analysis_run_id=str(uuid.uuid4()),
            key=key,
            source_event_id=event.event_id,
            correlation_id=event.correlation_id,
            status=PhysicalRunStatus.RUNNING,
            feature_set=None,
            public_result=None,
            private_trace=(),
            error_code=None,
            started_at=datetime.now(UTC),
            completed_at=None,
        )
        reserved = self.repository.reserve(candidate)
        if reserved.analysis_run_id != candidate.analysis_run_id:
            return reserved
        try:
            session = self.loader.load(event)
            if session.session_id != event.session_id:
                raise ValueError("physical session identity does not match event")
            if session.schema_version != event.input_schema_version:
                raise ValueError("physical session schema does not match event")
            profile = session.measurement_profile
            if profile.measurement_conformance_version != event.measurement_conformance_version:
                raise ValueError("measurement conformance does not match event")
            if profile.uncertainty_profile_version != event.uncertainty_profile_version:
                raise ValueError("uncertainty profile does not match event")
            validate_physical_pressure_session(session)
            feature_set: SessionFeatureSet = extract_features(session, self.parameters)
            ready = replace(
                candidate,
                status=PhysicalRunStatus.FEATURES_READY,
                feature_set=feature_set,
            )
            self.repository.save(ready)
            return ready
        except Exception:
            failed = replace(
                candidate,
                status=PhysicalRunStatus.FAILED,
                private_trace=("PHYSICAL_INPUT_FAILURE",),
                error_code="E-ALG-PHYSICAL-INPUT",
                completed_at=datetime.now(UTC),
            )
            self.repository.save(failed)
            return failed
