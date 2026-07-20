from __future__ import annotations

from datetime import UTC, datetime

import numpy as np

from client.local_analysis.models import (
    AnalysisContext,
    CalibrationState,
    LocalQualityStatus,
)
from client.local_analysis.service import (
    AnalysisAuthority,
    LocalAnalysisProcessor,
    ProcessingStatus,
    ReliableSessionData,
    StoredLocalAnalysis,
)
from client.reporting.models import BasicReportDocument, ReportStatus


def _frames() -> np.ndarray:
    frames = np.zeros((120, 48, 64), dtype=np.float64)
    frames[:, 20, 10] = 1000.0
    frames[:, 20, 53] = 1000.0
    return frames


def _session(quality: LocalQualityStatus = LocalQualityStatus.VALID) -> ReliableSessionData:
    return ReliableSessionData(
        session_id="session-1",
        subject_display_id="受试者 **1234",
        captured_at=datetime(2026, 7, 20, 10, 0, tzinfo=UTC),
        frames=_frames(),
        context=AnalysisContext(
            sample_rate_hz=12.0,
            duration_seconds=30.0,
            protocol_id="standard-static-bilateral",
            protocol_version="1.0.0-pilot",
            calibration_state=CalibrationState.RELATIVE_ONLY,
            quality_status=quality,
        ),
        reliable_storage_complete=True,
    )


class _Source:
    def __init__(self, data: ReliableSessionData) -> None:
        self.data = data
        self.reads = 0

    def read_reliable_session(self, session_id: str) -> ReliableSessionData:
        assert session_id == self.data.session_id
        self.reads += 1
        return self.data


class _AnalysisStore:
    def __init__(self) -> None:
        self.saved: dict[tuple[str, str], StoredLocalAnalysis] = {}

    def find(self, *, session_id: str, algorithm_version: str):
        return self.saved.get((session_id, algorithm_version))

    def save_if_absent(self, *, session_id: str, result):
        key = (session_id, result.algorithm_version)
        stored = self.saved.get(key)
        if stored is None:
            stored = StoredLocalAnalysis(
                analysis_result_id="local-analysis-1",
                version=1,
                session_id=session_id,
                authority=AnalysisAuthority.LOCAL_SUPPORTING,
                result=result,
            )
            self.saved[key] = stored
        return stored


class _ReportStore:
    def __init__(self) -> None:
        self.saved: dict[str, BasicReportDocument] = {}

    def find_basic_by_analysis(self, analysis_result_id: str):
        return self.saved.get(analysis_result_id)

    def reserve_report_identity(self, session_id: str) -> tuple[str, int]:
        assert session_id == "session-1"
        return ("report-1", 1)

    def save_if_absent(self, document: BasicReportDocument) -> BasicReportDocument:
        return self.saved.setdefault(document.analysis_result_id, document)


def _processor(data: ReliableSessionData):
    source = _Source(data)
    analyses = _AnalysisStore()
    reports = _ReportStore()
    processor = LocalAnalysisProcessor(
        source=source,
        analyses=analyses,
        reports=reports,
        clock=lambda: datetime(2026, 7, 20, 10, 1, tzinfo=UTC),
    )
    return processor, source, analyses, reports


def test_reliable_local_data_generates_versioned_basic_ready_without_network_dependency() -> None:
    processor, _, analyses, reports = _processor(_session())

    outcome = processor.process("session-1")

    assert outcome.status is ProcessingStatus.BASIC_READY
    assert outcome.analysis.version == 1
    assert outcome.analysis.authority is AnalysisAuthority.LOCAL_SUPPORTING
    assert outcome.report.report_id == "report-1"
    assert outcome.report.version == 1
    assert outcome.report.status is ReportStatus.BASIC_READY
    assert outcome.report.kind == "BASIC"
    assert {metric.key for metric in outcome.report.metrics} == {
        "total_relative_load",
        "left_load_percent",
        "right_load_percent",
    }
    assert "cop_path_length" not in {metric.key for metric in outcome.report.metrics}
    assert len(analyses.saved) == 1
    assert len(reports.saved) == 1


def test_invalid_quality_persists_result_but_never_generates_customer_report() -> None:
    processor, _, analyses, reports = _processor(
        _session(LocalQualityStatus.INVALID)
    )

    outcome = processor.process("session-1")

    assert outcome.status is ProcessingStatus.RETRY_REQUIRED
    assert outcome.analysis.result.quality_status is LocalQualityStatus.INVALID
    assert outcome.report is None
    assert len(analyses.saved) == 1
    assert reports.saved == {}


def test_processing_is_idempotent_and_does_not_reread_or_rewrite_immutable_results() -> None:
    processor, source, analyses, reports = _processor(_session())

    first = processor.process("session-1")
    second = processor.process("session-1")

    assert second is first
    assert source.reads == 1
    assert len(analyses.saved) == 1
    assert len(reports.saved) == 1

    restarted_source = _Source(_session())
    restarted = LocalAnalysisProcessor(
        source=restarted_source,
        analyses=analyses,
        reports=reports,
        clock=lambda: datetime(2030, 1, 1, tzinfo=UTC),
    )
    after_restart = restarted.process("session-1")
    assert after_restart.report is first.report
    assert restarted_source.reads == 0


def test_local_upload_snapshot_is_explicitly_non_authoritative_and_requires_cloud_raw_recompute() -> None:
    processor, _, _, _ = _processor(_session())
    outcome = processor.process("session-1")

    snapshot = outcome.analysis.to_upload_snapshot()

    assert snapshot.authority == "SUPPORTING_NON_AUTHORITATIVE"
    assert snapshot.cloud_recompute_from_raw is True
    assert snapshot.session_id == "session-1"
    assert snapshot.algorithm_version == "local-basic/1.0.0"


def test_unreliable_or_incomplete_local_storage_is_rejected_before_analysis() -> None:
    data = _session()
    incomplete = ReliableSessionData(
        session_id=data.session_id,
        subject_display_id=data.subject_display_id,
        captured_at=data.captured_at,
        frames=data.frames,
        context=data.context,
        reliable_storage_complete=False,
    )
    processor, _, analyses, reports = _processor(incomplete)

    outcome = processor.process("session-1")

    assert outcome.status is ProcessingStatus.SOURCE_NOT_RELIABLE
    assert outcome.analysis is None
    assert outcome.report is None
    assert analyses.saved == {}
    assert reports.saved == {}
