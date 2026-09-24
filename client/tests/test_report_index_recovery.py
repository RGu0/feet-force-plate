from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from client.app.institution_store import InstitutionLocalStore
from client.app.report_index_recovery import recover_missing_screening_records
from client.local_analysis.models import (
    LocalAnalysisResult,
    LocalMetricValue,
    LocalQualityStatus,
    LocalStageProjection,
)
from client.local_analysis.service import queue_supporting_local_analysis
from client.workflow.consent import ConsentRequest
from client.workflow.models import ScreeningParticipantContext
from client.workflow.participant import AnalysisProfile, CreateSubjectRequest
from client.workflow.protocol import default_standard_protocol



class _Key:
    def get_key(self) -> bytes:
        return b"i" * 32


class _Signer:
    def sign(self, _request, *, consent_record_id: str, granted_at: datetime) -> str:
        return f"signed:{consent_record_id}:{granted_at.isoformat()}"


class _PhysicalStore:
    def __init__(self, *, session_id: str, subject_uuid: str, payload: bytes) -> None:
        self._session_id = session_id
        self._subject_uuid = subject_uuid
        self._payload = payload

    def supporting_local_analysis(self, session_id: str) -> bytes:
        if session_id != self._session_id:
            raise KeyError(session_id)
        return self._payload

    def completed_valid_session_identity(self, session_id: str) -> tuple[str, int]:
        if session_id != self._session_id:
            raise KeyError(session_id)
        return self._subject_uuid, 1_795_309_200_000_000_000


class _Handoff:
    payload = b""

    def attach_supporting_local_analysis(self, _session_id: str, plaintext: bytes) -> None:
        self.payload = plaintext


def _supporting_payload(session_id: str) -> bytes:
    metric = LocalMetricValue("total_relative_load", 100.0, "%", "metric/1")
    stage_metric = LocalMetricValue("left_load_percent", 50.0, "%", "metric/1")
    heatmap = ((0.2, 0.8),)
    result = LocalAnalysisResult(
        result_version=1,
        algorithm_version="local-basic/1.0.0",
        protocol_id="standard-static-balance",
        protocol_version="static-balance/1",
        source_frame_count=1600,
        quality_status=LocalQualityStatus.VALID,
        raw_count_heatmap=None,
        relative_heatmap=heatmap,
        customer_metrics=(metric,),
        internal_metrics=(),
        withheld_metrics=(),
        stage_projections=tuple(
            LocalStageProjection(stage_id, heatmap, (stage_metric,))
            for stage_id in (
                "BILATERAL_EYES_OPEN",
                "BILATERAL_EYES_CLOSED",
                "SEMI_TANDEM_LEFT_FORWARD",
                "SEMI_TANDEM_RIGHT_FORWARD",
            )
        ),
    )
    handoff = _Handoff()
    queue_supporting_local_analysis(
        handoff,
        session_id=session_id,
        analysis_result_id="analysis-retained",
        version=1,
        result=result,
    )
    return handoff.payload


def test_retained_local_analysis_rebuilds_missing_record_once(tmp_path: Path) -> None:
    institution = InstitutionLocalStore.open(
        tmp_path,
        key_provider=_Key(),
        query_index_key=b"q" * 32,
        consent_signer=_Signer(),
    )
    subject = institution.create(
        CreateSubjectRequest(
            tenant_id="tenant-1",
            analysis_profile=AnalysisProfile.unknown(),
        )
    )
    consent = institution.create_consent(
        ConsentRequest(
            tenant_id="tenant-1",
            terminal_id="terminal-1",
            subject_uuid=subject.subject_uuid,
            policy_version="consent/1",
            purpose_codes=("SCREENING",),
            data_categories=("SCREENING",),
            evidence_type="OPERATOR_CONFIRMED",
        )
    )
    session_id = institution.create_engineering_session(
        ScreeningParticipantContext(subject.subject_uuid, consent.consent_record_id),
        default_standard_protocol().snapshot(),
    )
    institution.finalize(session_id)
    physical = _PhysicalStore(
        session_id=session_id,
        subject_uuid=subject.subject_uuid,
        payload=_supporting_payload(session_id),
    )

    first = recover_missing_screening_records(
        institution=institution,
        physical_store=physical,
        tenant_id="tenant-1",
        now=lambda: datetime(2026, 9, 22, 9, 0, tzinfo=UTC),
    )
    second = recover_missing_screening_records(
        institution=institution,
        physical_store=physical,
        tenant_id="tenant-1",
        now=lambda: datetime(2026, 9, 22, 9, 1, tzinfo=UTC),
    )

    assert first.recovered_count == 1
    assert second.recovered_count == 0
    rows = institution.recent_records(tenant_id="tenant-1")
    assert len(rows) == 1
    assert rows[0].screening_label == "静态平衡筛查"
    assert rows[0].report_id is not None
    document = institution.load_report(rows[0].report_id, rows[0].report_version or 0)
    assert '"analysis_result_id":"analysis-retained"' in document
    institution.close()
