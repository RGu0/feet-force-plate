from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from numpy import number
from numpy.typing import NDArray

from client.reporting.models import BasicReportDocument, ReportMetric, ReportStatus
from client.reporting.copy import BASIC_REPORT_DISCLAIMER, BASIC_REPORT_SUMMARY

from .analyzer import analyze_local
from .models import AnalysisContext, LocalAnalysisResult, LocalQualityStatus


@dataclass(frozen=True, slots=True)
class ReliableSessionData:
    session_id: str
    subject_display_id: str
    captured_at: datetime
    frames: NDArray[number]
    context: AnalysisContext
    reliable_storage_complete: bool


class ReliableSessionSourcePort(Protocol):
    def read_reliable_session(self, session_id: str) -> ReliableSessionData: ...


class AnalysisAuthority(StrEnum):
    LOCAL_SUPPORTING = "LOCAL_SUPPORTING"


@dataclass(frozen=True, slots=True)
class LocalAnalysisUploadSnapshot:
    session_id: str
    analysis_result_id: str
    version: int
    algorithm_version: str
    authority: str
    cloud_recompute_from_raw: bool
    result: LocalAnalysisResult


@dataclass(frozen=True, slots=True)
class StoredLocalAnalysis:
    analysis_result_id: str
    version: int
    session_id: str
    authority: AnalysisAuthority
    result: LocalAnalysisResult

    def to_upload_snapshot(self) -> LocalAnalysisUploadSnapshot:
        return LocalAnalysisUploadSnapshot(
            session_id=self.session_id,
            analysis_result_id=self.analysis_result_id,
            version=self.version,
            algorithm_version=self.result.algorithm_version,
            authority="SUPPORTING_NON_AUTHORITATIVE",
            cloud_recompute_from_raw=True,
            result=self.result,
        )


class LocalAnalysisStorePort(Protocol):
    def find(
        self,
        *,
        session_id: str,
        algorithm_version: str,
    ) -> StoredLocalAnalysis | None: ...

    def save_if_absent(
        self,
        *,
        session_id: str,
        result: LocalAnalysisResult,
    ) -> StoredLocalAnalysis: ...


class BasicReportStorePort(Protocol):
    def find_basic_by_analysis(
        self,
        analysis_result_id: str,
    ) -> BasicReportDocument | None: ...

    def reserve_report_identity(self, session_id: str) -> tuple[str, int]: ...

    def save_if_absent(
        self,
        document: BasicReportDocument,
    ) -> BasicReportDocument: ...


class ProcessingStatus(StrEnum):
    BASIC_READY = "BASIC_READY"
    RETRY_REQUIRED = "RETRY_REQUIRED"
    SOURCE_NOT_RELIABLE = "SOURCE_NOT_RELIABLE"


@dataclass(frozen=True, slots=True)
class ProcessingOutcome:
    status: ProcessingStatus
    analysis: StoredLocalAnalysis | None
    report: BasicReportDocument | None


_REPORT_LABELS = {
    "total_relative_load": "总相对载荷",
    "left_load_percent": "左侧相对负重",
    "right_load_percent": "右侧相对负重",
}
_ALGORITHM_VERSION = "local-basic/1.0.0"


class LocalAnalysisProcessor:
    """Offline orchestration; intentionally has no upload or network dependency."""

    def __init__(
        self,
        *,
        source: ReliableSessionSourcePort,
        analyses: LocalAnalysisStorePort,
        reports: BasicReportStorePort,
        clock: Callable[[], datetime],
    ) -> None:
        self._source = source
        self._analyses = analyses
        self._reports = reports
        self._clock = clock
        self._outcomes: dict[str, ProcessingOutcome] = {}

    def process(self, session_id: str) -> ProcessingOutcome:
        cached = self._outcomes.get(session_id)
        if cached is not None:
            return cached
        stored = self._analyses.find(
            session_id=session_id,
            algorithm_version=_ALGORITHM_VERSION,
        )
        if stored is not None:
            existing_report = self._reports.find_basic_by_analysis(
                stored.analysis_result_id
            )
            if existing_report is not None:
                return self._remember(
                    session_id,
                    ProcessingOutcome(
                        ProcessingStatus.BASIC_READY,
                        stored,
                        existing_report,
                    ),
                )
            if stored.result.quality_status is not LocalQualityStatus.VALID:
                return self._remember(
                    session_id,
                    ProcessingOutcome(ProcessingStatus.RETRY_REQUIRED, stored, None),
                )
        data = self._source.read_reliable_session(session_id)
        if not data.reliable_storage_complete:
            return self._remember(
                session_id,
                ProcessingOutcome(ProcessingStatus.SOURCE_NOT_RELIABLE, None, None),
            )
        if stored is None:
            result = analyze_local(data.frames, data.context)
            stored = self._analyses.save_if_absent(
                session_id=session_id,
                result=result,
            )
        else:
            result = stored.result
        if result.quality_status is not LocalQualityStatus.VALID:
            return self._remember(
                session_id,
                ProcessingOutcome(ProcessingStatus.RETRY_REQUIRED, stored, None),
            )
        existing_report = self._reports.find_basic_by_analysis(
            stored.analysis_result_id
        )
        if existing_report is not None:
            return self._remember(
                session_id,
                ProcessingOutcome(
                    ProcessingStatus.BASIC_READY,
                    stored,
                    existing_report,
                ),
            )
        if result.relative_heatmap is None:
            raise RuntimeError("valid local analysis requires a relative heatmap")
        report_id, version = self._reports.reserve_report_identity(session_id)
        document = BasicReportDocument(
            report_id=report_id,
            version=version,
            status=ReportStatus.BASIC_READY,
            kind="BASIC",
            session_id=session_id,
            analysis_result_id=stored.analysis_result_id,
            subject_display_id=data.subject_display_id,
            captured_at=data.captured_at,
            generated_at=self._clock(),
            protocol_id=result.protocol_id,
            protocol_version=result.protocol_version,
            metrics=tuple(
                ReportMetric(
                    key=metric.key,
                    label=_REPORT_LABELS[metric.key],
                    value=metric.value,
                    unit=metric.unit,
                    definition_version=metric.definition_version,
                )
                for metric in result.customer_metrics
                if metric.key in _REPORT_LABELS
            ),
            relative_heatmap=result.relative_heatmap,
            summary=BASIC_REPORT_SUMMARY,
            disclaimer=BASIC_REPORT_DISCLAIMER,
            provenance=(result.algorithm_version, "report-schema/1.0.0"),
        )
        report = self._reports.save_if_absent(document)
        return self._remember(
            session_id,
            ProcessingOutcome(ProcessingStatus.BASIC_READY, stored, report),
        )

    def _remember(
        self,
        session_id: str,
        outcome: ProcessingOutcome,
    ) -> ProcessingOutcome:
        self._outcomes[session_id] = outcome
        return outcome
