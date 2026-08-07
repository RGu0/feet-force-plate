from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import StrEnum
import json
from pathlib import Path
from typing import Protocol

from numpy import number
from numpy.typing import NDArray

from client.reporting.models import (
    BasicReportDocument,
    ReportMetric,
    ReportStage,
    ReportStatus,
)
from client.reporting.copy import (
    BASIC_REPORT_DISCLAIMER,
    BASIC_REPORT_SUMMARY,
    PHYSICAL_RELATIVE_REPORT_SUMMARY,
)
from client.spool.state_store import KeyProvider, StateStore
from cloud.analysis.feature_parameters import FeatureParameters
from cloud.analysis.protocol_context import StaticBalanceProtocolContext

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

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "local-analysis-upload-snapshot/1",
            "session_id": self.session_id,
            "analysis_result_id": self.analysis_result_id,
            "version": self.version,
            "algorithm_version": self.algorithm_version,
            "authority": self.authority,
            "cloud_recompute_from_raw": self.cloud_recompute_from_raw,
            "result": asdict(self.result),
        }

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )


class SupportingAnalysisHandoffPort(Protocol):
    def attach_supporting_local_analysis(
        self,
        session_id: str,
        plaintext: bytes,
    ) -> None: ...


def queue_supporting_local_analysis(
    handoff: SupportingAnalysisHandoffPort,
    *,
    session_id: str,
    analysis_result_id: str,
    version: int,
    result: LocalAnalysisResult,
) -> LocalAnalysisUploadSnapshot:
    """Queue a supporting result while preserving raw/cloud authority."""

    if not session_id or not analysis_result_id or version <= 0:
        raise ValueError("analysis handoff identity and positive version are required")
    if result.raw_count_heatmap is not None:
        raise ValueError("supporting analysis handoff cannot contain raw-count heatmaps")
    snapshot = LocalAnalysisUploadSnapshot(
        session_id=session_id,
        analysis_result_id=analysis_result_id,
        version=version,
        algorithm_version=result.algorithm_version,
        authority="SUPPORTING_NON_AUTHORITATIVE",
        cloud_recompute_from_raw=True,
        result=result,
    )
    handoff.attach_supporting_local_analysis(
        session_id,
        snapshot.to_json().encode("utf-8"),
    )
    return snapshot


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


@dataclass(frozen=True, slots=True)
class PhysicalLocalProcessingOutcome:
    result: LocalAnalysisResult
    report: BasicReportDocument
    snapshot: LocalAnalysisUploadSnapshot


_REPORT_LABELS = {
    "total_relative_load": "总相对载荷",
    "left_load_percent": "左侧相对负重",
    "right_load_percent": "右侧相对负重",
}
_STAGE_TITLES = {
    "BILATERAL_EYES_OPEN": "第一段：并足睁眼",
    "BILATERAL_EYES_CLOSED": "第二段：并足闭眼",
    "SEMI_TANDEM_LEFT_FORWARD": "第三段：左脚在前半串联",
    "SEMI_TANDEM_RIGHT_FORWARD": "第四段：右脚在前半串联",
}
_STAGE_REPORT_LABELS = {
    "left_load_percent": "左侧相对负载",
    "right_load_percent": "右侧相对负载",
    "anterior_load_percent": "前侧相对负载",
    "posterior_load_percent": "后侧相对负载",
    "cop_path_mm": "COP 路径长度",
    "cop_mean_velocity_mm_s": "COP 平均速度",
    "cop_ml_range_90_mm": "COP ML 90% 范围",
    "cop_ap_range_90_mm": "COP AP 90% 范围",
    "cop_ml_mean_velocity_mm_s": "COP ML 平均速度",
    "cop_ap_mean_velocity_mm_s": "COP AP 平均速度",
    "cop_ellipse_area_95_mm2": "COP 95% 椭圆面积",
}
_ALGORITHM_VERSION = "local-basic/1.0.0"


def build_basic_report_document(
    result: LocalAnalysisResult,
    *,
    report_id: str,
    version: int,
    session_id: str,
    analysis_result_id: str,
    subject_display_id: str,
    captured_at: datetime,
    generated_at: datetime,
) -> BasicReportDocument:
    """Map only a release-gated local result into a nondiagnostic BASIC report."""

    if result.quality_status is not LocalQualityStatus.VALID:
        raise ValueError("BASIC_READY requires a VALID local analysis result")
    if result.relative_heatmap is None:
        raise ValueError("BASIC_READY requires a release-gated relative heatmap")
    report_metrics = tuple(
        ReportMetric(
            key=metric.key,
            label=_REPORT_LABELS[metric.key],
            value=metric.value,
            unit=metric.unit,
            definition_version=metric.definition_version,
        )
        for metric in result.customer_metrics
        if metric.key in _REPORT_LABELS
    )
    if not report_metrics:
        raise ValueError("BASIC_READY requires at least one approved customer metric")
    report_stages = tuple(
        ReportStage(
            stage_id=stage.stage_id,
            title=_STAGE_TITLES[stage.stage_id],
            relative_heatmap=stage.relative_heatmap,
            metrics=tuple(
                ReportMetric(
                    key=metric.key,
                    label=_STAGE_REPORT_LABELS[metric.key],
                    value=metric.value,
                    unit=metric.unit,
                    definition_version=metric.definition_version,
                )
                for metric in stage.metrics
                if metric.key in _STAGE_REPORT_LABELS
            ),
        )
        for stage in result.stage_projections
    )
    if result.protocol_id == "standard-static-balance" and len(report_stages) != 4:
        raise ValueError("physical BASIC_READY requires four stage projections")
    metric_keys = {metric.key for metric in report_metrics}
    summary = (
        BASIC_REPORT_SUMMARY
        if "total_relative_load" in metric_keys
        else PHYSICAL_RELATIVE_REPORT_SUMMARY
    )
    return BasicReportDocument(
        report_id=report_id,
        version=version,
        status=ReportStatus.BASIC_READY,
        kind="BASIC",
        session_id=session_id,
        analysis_result_id=analysis_result_id,
        subject_display_id=subject_display_id,
        captured_at=captured_at,
        generated_at=generated_at,
        protocol_id=result.protocol_id,
        protocol_version=result.protocol_version,
        metrics=report_metrics,
        relative_heatmap=result.relative_heatmap,
        summary=summary,
        disclaimer=BASIC_REPORT_DISCLAIMER,
        provenance=(result.algorithm_version, "report-schema/2.0.0"),
        stages=report_stages,
    )


def process_committed_physical_session(
    root: str | Path,
    *,
    session_id: str,
    store: StateStore,
    key_provider: KeyProvider,
    protocol_context: StaticBalanceProtocolContext,
    parameters: FeatureParameters,
    report_id: str,
    report_version: int,
    analysis_result_id: str,
    subject_display_id: str,
    captured_at: datetime,
    generated_at: datetime,
) -> PhysicalLocalProcessingOutcome:
    """Compose committed physical input, BASIC report, and supporting sync handoff."""

    from .physical import analyze_committed_physical_session

    result = analyze_committed_physical_session(
        root,
        session_id=session_id,
        store=store,
        key_provider=key_provider,
        protocol_context=protocol_context,
        parameters=parameters,
    )
    report = build_basic_report_document(
        result,
        report_id=report_id,
        version=report_version,
        session_id=session_id,
        analysis_result_id=analysis_result_id,
        subject_display_id=subject_display_id,
        captured_at=captured_at,
        generated_at=generated_at,
    )
    snapshot = queue_supporting_local_analysis(
        store,
        session_id=session_id,
        analysis_result_id=analysis_result_id,
        version=report_version,
        result=result,
    )
    return PhysicalLocalProcessingOutcome(
        result=result,
        report=report,
        snapshot=snapshot,
    )


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
        report_id, version = self._reports.reserve_report_identity(session_id)
        document = build_basic_report_document(
            result,
            report_id=report_id,
            version=version,
            session_id=session_id,
            analysis_result_id=stored.analysis_result_id,
            subject_display_id=data.subject_display_id,
            captured_at=data.captured_at,
            generated_at=self._clock(),
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
