"""Restore missing institution record rows from retained local analysis results."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
from typing import Protocol

from client.local_analysis.models import (
    LocalAnalysisResult,
    LocalMetricValue,
    LocalQualityStatus,
    LocalStageProjection,
    WithheldMetric,
)
from client.local_analysis.service import build_basic_report_document

from .institution_store import InstitutionLocalStore


class _PhysicalRecoveryStore(Protocol):
    def supporting_local_analysis(self, session_id: str) -> bytes: ...

    def completed_valid_session_identity(self, session_id: str) -> tuple[str, int]: ...


@dataclass(frozen=True, slots=True)
class RecordRecoveryResult:
    candidate_count: int
    recovered_count: int
    unavailable_count: int


def recover_missing_screening_records(
    *,
    institution: InstitutionLocalStore,
    physical_store: _PhysicalRecoveryStore,
    tenant_id: str,
    now: Callable[[], datetime] | None = None,
) -> RecordRecoveryResult:
    """Rebuild record rows without replaying acquisition or crossing tenants."""

    candidates = institution.completed_sessions_missing_records(tenant_id=tenant_id)
    recovered = 0
    unavailable = 0
    clock = now or (lambda: datetime.now(UTC))
    for candidate in candidates:
        try:
            subject_uuid, started_at_ns = physical_store.completed_valid_session_identity(
                candidate.session_id
            )
            payload = physical_store.supporting_local_analysis(candidate.session_id)
            analysis_result_id, version, result = _restore_supporting_result(
                payload,
                expected_session_id=candidate.session_id,
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            unavailable += 1
            continue
        if subject_uuid != candidate.subject_uuid:
            unavailable += 1
            continue
        report = build_basic_report_document(
            result,
            report_id=_recovered_report_id(candidate.session_id),
            version=version,
            session_id=candidate.session_id,
            analysis_result_id=analysis_result_id,
            subject_display_id=f"匿名 {subject_uuid[-6:]}",
            captured_at=datetime.fromtimestamp(started_at_ns / 1_000_000_000, tz=UTC),
            generated_at=clock(),
        )
        institution.save_report(report)
        recovered += 1
    return RecordRecoveryResult(len(candidates), recovered, unavailable)


def _recovered_report_id(session_id: str) -> str:
    digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:12]
    return f"basic-recovered-{digest}"


def _restore_supporting_result(
    payload: bytes,
    *,
    expected_session_id: str,
) -> tuple[str, int, LocalAnalysisResult]:
    value = json.loads(payload)
    if (
        value.get("schema_version") != "local-analysis-upload-snapshot/1"
        or value.get("session_id") != expected_session_id
        or value.get("authority") != "SUPPORTING_NON_AUTHORITATIVE"
        or value.get("cloud_recompute_from_raw") is not True
    ):
        raise ValueError("retained local analysis identity is invalid")
    analysis_result_id = value.get("analysis_result_id")
    version = value.get("version")
    if not isinstance(analysis_result_id, str) or not analysis_result_id:
        raise ValueError("retained analysis result identity is required")
    if not isinstance(version, int) or version <= 0:
        raise ValueError("retained analysis version must be positive")
    raw_result = value.get("result")
    if not isinstance(raw_result, dict):
        raise ValueError("retained local analysis result is missing")
    result = _restore_result(raw_result)
    if result.quality_status is not LocalQualityStatus.VALID:
        raise ValueError("only valid retained analyses can restore records")
    return analysis_result_id, version, result


def _matrix(value: object) -> tuple[tuple[float, ...], ...] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise ValueError("analysis heatmap must be a matrix")
    return tuple(tuple(float(cell) for cell in row) for row in value)


def _metric(value: object) -> LocalMetricValue:
    if not isinstance(value, dict):
        raise ValueError("analysis metric must be an object")
    return LocalMetricValue(
        key=str(value["key"]),
        value=float(value["value"]),
        unit=str(value["unit"]),
        definition_version=str(value["definition_version"]),
    )


def _restore_result(value: dict[str, object]) -> LocalAnalysisResult:
    stages = value.get("stage_projections", [])
    if not isinstance(stages, list):
        raise ValueError("stage projections must be a list")
    customer_metrics = value.get("customer_metrics", [])
    internal_metrics = value.get("internal_metrics", [])
    withheld_metrics = value.get("withheld_metrics", [])
    if not all(
        isinstance(items, list)
        for items in (customer_metrics, internal_metrics, withheld_metrics)
    ):
        raise ValueError("analysis metric collections must be lists")
    return LocalAnalysisResult(
        result_version=int(value["result_version"]),
        algorithm_version=str(value["algorithm_version"]),
        protocol_id=str(value["protocol_id"]),
        protocol_version=str(value["protocol_version"]),
        source_frame_count=int(value["source_frame_count"]),
        quality_status=LocalQualityStatus(str(value["quality_status"])),
        raw_count_heatmap=_matrix(value.get("raw_count_heatmap")),
        relative_heatmap=_matrix(value.get("relative_heatmap")),
        customer_metrics=tuple(_metric(metric) for metric in customer_metrics),
        internal_metrics=tuple(_metric(metric) for metric in internal_metrics),
        withheld_metrics=tuple(
            WithheldMetric(str(metric["key"]), str(metric["reason"]))
            for metric in withheld_metrics
            if isinstance(metric, dict)
        ),
        stage_projections=tuple(
            LocalStageProjection(
                stage_id=str(stage["stage_id"]),
                relative_heatmap=_matrix(stage["relative_heatmap"]) or (),
                metrics=tuple(_metric(metric) for metric in stage.get("metrics", [])),
            )
            for stage in stages
            if isinstance(stage, dict)
        ),
    )
