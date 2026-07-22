from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class PhysicalRunStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    FEATURES_READY = "FEATURES_READY"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    UNSUPPORTED = "UNSUPPORTED"
    CANCELED = "CANCELED"


@dataclass(frozen=True, slots=True)
class PhysicalAnalysisRunKey:
    tenant_id: str
    session_id: str
    input_manifest_sha256: str
    hardware_adapter_version: str
    input_schema_version: str
    measurement_conformance_version: str
    uncertainty_profile_version: str
    test_protocol_version: str
    feature_pipeline_version: str
    feature_parameters_sha256: str
    rule_set_version: str
    reference_population_id: str
    reference_artifact_sha256: str
    questionnaire_snapshot_sha256: str
    result_schema_version: str

    @property
    def identity_sha256(self) -> str:
        encoded = json.dumps(
            asdict(self),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class PhysicalAnalysisRun:
    analysis_run_id: str
    key: PhysicalAnalysisRunKey
    source_event_id: str
    correlation_id: str
    status: PhysicalRunStatus
    feature_set: object | None
    public_result: object | None
    private_trace: tuple[str, ...]
    error_code: str | None
    started_at: datetime
    completed_at: datetime | None


class InMemoryPhysicalAnalysisRepository:
    """Reference repository for the immutable run identity boundary."""

    _terminal_statuses = frozenset(
        {
            PhysicalRunStatus.SUCCEEDED,
            PhysicalRunStatus.FAILED,
            PhysicalRunStatus.UNSUPPORTED,
            PhysicalRunStatus.CANCELED,
        }
    )

    def __init__(self) -> None:
        self._runs: dict[PhysicalAnalysisRunKey, PhysicalAnalysisRun] = {}
        self._lock = threading.RLock()

    def get(self, key: PhysicalAnalysisRunKey) -> PhysicalAnalysisRun | None:
        with self._lock:
            return self._runs.get(key)

    def reserve(self, run: PhysicalAnalysisRun) -> PhysicalAnalysisRun:
        with self._lock:
            existing = self._runs.get(run.key)
            if existing is not None:
                return existing
            self._runs[run.key] = run
            return run

    def save(self, run: PhysicalAnalysisRun) -> None:
        with self._lock:
            existing = self._runs.get(run.key)
            if existing is None or existing.analysis_run_id != run.analysis_run_id:
                raise ValueError("physical analysis run was not reserved by this worker")
            if existing.status in self._terminal_statuses and existing != run:
                raise ValueError("terminal physical analysis runs are immutable")
            self._runs[run.key] = run

    def count(self) -> int:
        with self._lock:
            return len(self._runs)
