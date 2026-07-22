from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from statistics import median
from typing import Protocol

from cloud.analysis.feature_parameters import FeatureParameters
from cloud.analysis.features import SessionFeatureSet, extract_features
from cloud.analysis.models import CapabilityStatus
from cloud.analysis.physical_gates import (
    PhysicalCapabilityContext,
    PhysicalMetricDescriptor,
    evaluate_risk_release_capability,
)
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
from cloud.analysis.risk_rules import (
    QuestionnaireSnapshot,
    evaluate_screening_risk,
    questionnaire_snapshot_sha256,
)


class QuestionnaireIdentityError(ValueError):
    """The loaded questionnaire does not match the immutable event identity."""


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
    calibration_profile_version: str
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


class QuestionnaireLoader(Protocol):
    def load(self, event: CompleteSessionEvent) -> QuestionnaireSnapshot: ...


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


class InMemoryQuestionnaireLoader:
    def __init__(
        self,
        questionnaire: QuestionnaireSnapshot | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.questionnaire = questionnaire
        self.error = error

    def load(self, event: CompleteSessionEvent) -> QuestionnaireSnapshot:
        if self.error is not None:
            raise self.error
        if self.questionnaire is None:
            raise ValueError("questionnaire snapshot is unavailable")
        return self.questionnaire


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
        release_descriptor: PhysicalMetricDescriptor,
        questionnaire_loader: QuestionnaireLoader,
    ) -> None:
        self.loader = loader
        self.repository = repository
        self.parameters = parameters
        self.release_descriptor = release_descriptor
        self.questionnaire_loader = questionnaire_loader

    def _capability_context(
        self,
        *,
        session: PhysicalPressureSession,
        features: SessionFeatureSet,
        event: CompleteSessionEvent,
    ) -> PhysicalCapabilityContext:
        valid_timestamps = tuple(
            timestamp
            for stage in features.stages
            for timestamp in stage.timestamps_s
        )
        deltas = tuple(
            right - left
            for left, right in zip(valid_timestamps, valid_timestamps[1:])
            if right > left
        )
        nominal_interval = median(deltas) if deltas else 0.0
        sample_rate = 1.0 / nominal_interval if nominal_interval > 0 else 0.0
        max_gap = (
            max(deltas) / nominal_interval
            if nominal_interval > 0 and deltas
            else float("inf")
        )
        total_frames = sum(stage.total_frame_count for stage in features.stages)
        valid_frames = sum(stage.valid_frame_count for stage in features.stages)
        return PhysicalCapabilityContext(
            sample_rate_hz=sample_rate,
            valid_frame_ratio=valid_frames / total_frames if total_frames else 0.0,
            completed_valid_duration_s=min(
                stage.completion_time_s for stage in features.stages
            ),
            max_gap_nominal_intervals=max_gap,
            reference_artifact_sha256=event.reference_artifact_sha256,
            adapter_version=event.hardware_adapter_version,
            protocol_version=event.test_protocol_version,
            rule_set_version=event.rule_set_version,
        )

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
            calibration_profile_version=event.calibration_profile_version,
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
            if profile.calibration_profile_version != event.calibration_profile_version:
                raise ValueError("calibration profile does not match event")
            if profile.uncertainty_profile_version != event.uncertainty_profile_version:
                raise ValueError("uncertainty profile does not match event")
            validate_physical_pressure_session(session)
            feature_set: SessionFeatureSet = extract_features(session, self.parameters)
            if feature_set.pipeline_version != event.feature_pipeline_version:
                raise ValueError("feature pipeline does not match event")
            capability = evaluate_risk_release_capability(
                session=session,
                features=feature_set,
                context=self._capability_context(
                    session=session,
                    features=feature_set,
                    event=event,
                ),
                descriptor=self.release_descriptor,
            )
            if capability.status is not CapabilityStatus.SUPPORTED:
                unsupported = replace(
                    candidate,
                    status=PhysicalRunStatus.UNSUPPORTED,
                    feature_set=feature_set,
                    private_trace=capability.internal_reason_codes,
                    error_code="E-ALG-CAPABILITY",
                    capability_status=capability.status,
                    completed_at=datetime.now(UTC),
                )
                self.repository.save(unsupported)
                return unsupported
            questionnaire = self.questionnaire_loader.load(event)
            if questionnaire_snapshot_sha256(questionnaire) != event.questionnaire_snapshot_sha256:
                raise QuestionnaireIdentityError("questionnaire snapshot identity does not match event")
            risk = evaluate_screening_risk(
                session=session,
                features=feature_set,
                questionnaire=questionnaire,
            )
            succeeded = replace(
                candidate,
                status=PhysicalRunStatus.SUCCEEDED,
                feature_set=feature_set,
                public_result=risk,
                capability_status=capability.status,
                completed_at=datetime.now(UTC),
            )
            self.repository.save(succeeded)
            return succeeded
        except QuestionnaireIdentityError:
            failed = replace(
                candidate,
                status=PhysicalRunStatus.FAILED,
                private_trace=("QUESTIONNAIRE_IDENTITY_MISMATCH",),
                error_code="E-ALG-QUESTIONNAIRE",
                completed_at=datetime.now(UTC),
            )
            self.repository.save(failed)
            return failed
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
