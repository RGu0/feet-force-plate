from __future__ import annotations

import hashlib
import json
import math
import threading
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

from cloud.analysis.features import FeaturePipeline
from cloud.analysis.gates import evaluate_capability
from cloud.analysis.models import (
    AlgorithmDescriptor,
    AnalysisRun,
    AnalysisRunKey,
    AnalysisRunStatus,
    MetricResult,
    PublishedEvent,
    RawSession,
    SessionIngestedEvent,
)
from cloud.analysis.ports import (
    AnalysisEventPublisher,
    AnalysisRepository,
    CloudQualityAssessor,
    RawSessionLoader,
)


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class RegisteredMetric:
    descriptor: AlgorithmDescriptor
    compute: Callable[[Any], float]


class InMemoryAnalysisRepository:
    """Thread-safe reference adapter that mirrors the database uniqueness boundary."""

    def __init__(self) -> None:
        self._runs: dict[AnalysisRunKey, AnalysisRun] = {}
        self._lock = threading.RLock()

    def get(self, key: AnalysisRunKey) -> AnalysisRun | None:
        with self._lock:
            return self._runs.get(key)

    def reserve(self, run: AnalysisRun) -> AnalysisRun:
        with self._lock:
            existing = self._runs.get(run.key)
            if existing is not None:
                return existing
            self._runs[run.key] = run
            return run

    def save(self, run: AnalysisRun) -> None:
        with self._lock:
            existing = self._runs.get(run.key)
            if existing is None or existing.analysis_run_id != run.analysis_run_id:
                raise ValueError("analysis run was not reserved by this worker")
            if existing.status in {
                AnalysisRunStatus.SUCCEEDED,
                AnalysisRunStatus.FAILED,
                AnalysisRunStatus.UNSUPPORTED,
                AnalysisRunStatus.CANCELED,
            } and existing != run:
                raise ValueError("terminal analysis runs are immutable")
            self._runs[run.key] = run

    def count(self) -> int:
        with self._lock:
            return len(self._runs)


class InMemoryEventPublisher:
    def __init__(self) -> None:
        self.events: list[PublishedEvent] = []
        self._lock = threading.Lock()

    def publish(self, event: PublishedEvent) -> None:
        with self._lock:
            self.events.append(event)


class AnalysisOrchestrator:
    def __init__(
        self,
        *,
        loader: RawSessionLoader,
        quality_assessor: CloudQualityAssessor,
        feature_pipeline: FeaturePipeline,
        registered_metrics: Sequence[RegisteredMetric],
        repository: AnalysisRepository,
        publisher: AnalysisEventPublisher,
        algorithm_set_version: str,
        model_set_version: str,
        report_schema_version: str,
        parameters: Mapping[str, Any],
    ) -> None:
        self.loader = loader
        self.quality_assessor = quality_assessor
        self.feature_pipeline = feature_pipeline
        self.registered_metrics = tuple(registered_metrics)
        self.repository = repository
        self.publisher = publisher
        self.algorithm_set_version = algorithm_set_version
        self.model_set_version = model_set_version
        self.report_schema_version = report_schema_version
        self.parameters = dict(parameters)

    def handle(self, event: SessionIngestedEvent) -> AnalysisRun:
        if event.event_type != "session.ingested.v1":
            raise ValueError("analysis only accepts session.ingested.v1")
        if event.payload_schema_version.startswith("estimated-force-session/"):
            raise ValueError(
                "standard estimated-force sessions must be handled by PhysicalAnalysisOrchestrator"
            )

        key = AnalysisRunKey(
            tenant_id=event.tenant_id,
            session_id=event.session_id,
            pipeline_version=self.feature_pipeline.pipeline_version,
            algorithm_set_version=self.algorithm_set_version,
            model_set_version=self.model_set_version,
            report_schema_version=self.report_schema_version,
            calibration_version=event.calibration_version,
            payload_schema_version=event.payload_schema_version,
            protocol_profile_version=event.protocol_profile_version,
            input_manifest_sha256=event.manifest_sha256,
            parameters_sha256=_canonical_sha256(self.parameters),
        )
        existing = self.repository.get(key)
        if existing is not None:
            return existing

        started_at = datetime.now(UTC)
        candidate = AnalysisRun(
            analysis_run_id=str(uuid.uuid4()),
            key=key,
            source_event_id=event.event_id,
            correlation_id=event.correlation_id,
            report_schema_version=self.report_schema_version,
            status=AnalysisRunStatus.RUNNING,
            feature_set=None,
            metric_results=(),
            capability_reasons=(),
            error_code=None,
            started_at=started_at,
            completed_at=None,
        )
        reserved = self.repository.reserve(candidate)
        if reserved.analysis_run_id != candidate.analysis_run_id:
            return reserved

        self._publish("analysis.started.v1", candidate, event)
        try:
            raw_session = self.loader.load(event)
            self._validate_raw_session(event, raw_session)
            assessment = self.quality_assessor.assess(raw_session)
            assessed_context = replace(
                raw_session.context,
                cloud_quality_status=assessment.status,
                quality_flags=assessment.flags,
            )
            assessed_session = replace(raw_session, context=assessed_context)
            feature_set = self.feature_pipeline.extract(
                assessed_session,
                self.parameters,
            )

            metric_results: list[MetricResult] = []
            capability_reasons: list[tuple[str, tuple[str, ...]]] = []
            for registered in self.registered_metrics:
                decision = evaluate_capability(assessed_context, registered.descriptor)
                if not decision.publishable:
                    capability_reasons.append(
                        (decision.metric_id, decision.internal_reason_codes)
                    )
                    continue
                value = float(registered.compute(feature_set))
                if not math.isfinite(value):
                    raise ValueError("metric computation returned a non-finite value")
                descriptor = registered.descriptor
                metric_results.append(
                    MetricResult(
                        metric_id=descriptor.metric_id,
                        metric_definition_version=descriptor.metric_definition_version,
                        definition=descriptor.definition,
                        unit=descriptor.unit,
                        algorithm_id=descriptor.algorithm_id,
                        algorithm_version=descriptor.algorithm_version,
                        value_numeric=value,
                        validation_status=descriptor.validation_status,
                        feature_cache_key=feature_set.cache_key,
                    )
                )

            final_status = (
                AnalysisRunStatus.SUCCEEDED
                if metric_results
                else AnalysisRunStatus.UNSUPPORTED
            )
            completed = replace(
                candidate,
                status=final_status,
                feature_set=feature_set,
                metric_results=tuple(metric_results),
                capability_reasons=tuple(capability_reasons),
                completed_at=datetime.now(UTC),
            )
            self.repository.save(completed)
            if final_status is AnalysisRunStatus.SUCCEEDED:
                self._publish("analysis.completed.v1", completed, event)
            return completed
        except Exception:
            failed = replace(
                candidate,
                status=AnalysisRunStatus.FAILED,
                error_code="E-ALG-500",
                completed_at=datetime.now(UTC),
            )
            self.repository.save(failed)
            self._publish("analysis.failed.v1", failed, event)
            return failed

    @staticmethod
    def _validate_raw_session(
        event: SessionIngestedEvent,
        raw_session: RawSession,
    ) -> None:
        context = raw_session.context
        expected = (
            (context.tenant_id, event.tenant_id),
            (context.session_id, event.session_id),
            (context.manifest_sha256, event.manifest_sha256),
            (context.calibration_version, event.calibration_version),
        )
        if any(actual != announced for actual, announced in expected):
            raise ValueError("raw session context does not match the ingested event")
        if context.manifest_status != "VERIFIED":
            raise ValueError("raw session manifest is not verified")

    def _publish(
        self,
        event_type: str,
        run: AnalysisRun,
        source: SessionIngestedEvent,
    ) -> None:
        self.publisher.publish(
            PublishedEvent(
                event_type=event_type,
                tenant_id=run.key.tenant_id,
                aggregate_id=run.analysis_run_id,
                correlation_id=source.correlation_id,
                payload=(
                    ("analysis_run_id", run.analysis_run_id),
                    ("session_id", run.key.session_id),
                    ("status", run.status.value),
                    ("manifest_sha256", run.key.input_manifest_sha256),
                    ("error_code", run.error_code or ""),
                ),
            )
        )
