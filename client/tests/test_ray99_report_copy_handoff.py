from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import hashlib
import json
import sqlite3
from types import SimpleNamespace
from uuid import uuid4

import httpx

from client.app.institution_store import InstitutionLocalStore
from client.reporting.models import BasicReportDocument, ReportStatus
from client.sync.report_copy import ReportCopyOutcome, ReportCopyUploader
from client.sync.persistent_upload import HttpIngestionClient
from client.spool.state_store import StateStore


class _Key:
    def get_key(self) -> bytes:
        return b"r" * 32


class _Physical:
    def __init__(self, consent_id: str | None) -> None:
        self.consent_id = consent_id

    def report_copy_consent_id(self, _session_id: str) -> str | None:
        return self.consent_id


class _Renderer:
    def __init__(self) -> None:
        self.calls = 0

    def render(self, _report, destination: Path) -> None:
        self.calls += 1
        destination.write_bytes(b"%PDF-1.4\nsynthetic\n%%EOF\n")


class _Cloud:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.fail_after_commit = False

    def upload_basic_report_copy(self, _token: str, **payload) -> dict:
        self.calls.append(payload)
        if self.fail_after_commit:
            self.fail_after_commit = False
            from client.sync.persistent_upload import UploadRetryable
            raise UploadRetryable("response lost")
        return {name: payload[name] for name in (
            "report_id", "version", "document_sha256", "pdf_sha256",
        )}


class _Tokens:
    def current_access_token(self) -> str:
        return "test-token"

    def refresh(self):
        return None


def _report() -> BasicReportDocument:
    now = datetime.now(UTC)
    return BasicReportDocument(
        report_id="basic-abc123", version=1, status=ReportStatus.BASIC_READY,
        kind="BASIC", session_id=uuid4().hex, analysis_result_id="local-1",
        subject_display_id="synthetic", captured_at=now, generated_at=now,
        protocol_id="synthetic", protocol_version="1", metrics=(),
        relative_heatmap=((0.0,),), summary="synthetic", disclaimer="test",
        provenance=("synthetic",),
    )


def test_report_save_atomically_queues_an_encrypted_copy(tmp_path) -> None:
    local = InstitutionLocalStore.open(tmp_path, key_provider=_Key(), query_index_key=b"q" * 32)
    report = _report()
    local.save_report(report)
    with sqlite3.connect(local.path) as database:
        row = database.execute(
            "SELECT state, document_sha256 FROM institution_report_copy_handoffs WHERE session_id=?",
            (report.session_id,),
        ).fetchone()
    assert row is not None and row[0] == "PENDING"
    assert report.report_id not in local.path.read_text(errors="ignore")


def test_copy_waits_for_cloud_ingested_then_survives_lost_response_and_restart(tmp_path) -> None:
    local = InstitutionLocalStore.open(tmp_path, key_provider=_Key(), query_index_key=b"q" * 32)
    report = _report()
    local.save_report(report)
    physical = _Physical(None)
    cloud = _Cloud()
    renderer = _Renderer()
    uploader = ReportCopyUploader(local.path, _Key(), physical, cloud, renderer, now_ns=lambda: 1)
    assert uploader.run_once(_Tokens()) is ReportCopyOutcome.IDLE
    assert renderer.calls == 0 and cloud.calls == []
    physical.consent_id = str(uuid4())
    cloud.fail_after_commit = True
    assert uploader.run_once(_Tokens()) is ReportCopyOutcome.DEFERRED
    uploader.close()
    restarted = ReportCopyUploader(local.path, _Key(), physical, cloud, renderer, now_ns=lambda: 10**12)
    assert restarted.run_once(_Tokens()) is ReportCopyOutcome.CONFIRMED
    assert renderer.calls == 1
    assert cloud.calls[0] == cloud.calls[1]
    assert restarted.run_once(_Tokens()) is ReportCopyOutcome.IDLE
    assert local.load_report(report.report_id, 1) == report.to_json()
    restarted.close()


def test_changed_cloud_receipt_blocks_copy_without_erasing_local_report(tmp_path) -> None:
    local = InstitutionLocalStore.open(tmp_path, key_provider=_Key(), query_index_key=b"q" * 32)
    report = _report()
    local.save_report(report)
    physical = _Physical(str(uuid4()))

    class WrongCloud(_Cloud):
        def upload_basic_report_copy(self, token: str, **payload) -> dict:
            receipt = super().upload_basic_report_copy(token, **payload)
            receipt["pdf_sha256"] = "0" * 64
            return receipt

    uploader = ReportCopyUploader(local.path, _Key(), physical, WrongCloud(), _Renderer())
    assert uploader.run_once(_Tokens()) is ReportCopyOutcome.CONFLICT
    assert uploader.run_once(_Tokens()) is ReportCopyOutcome.IDLE
    assert local.load_report(report.report_id, 1) == report.to_json()
    uploader.close()


def test_http_adapter_sends_bound_copy_over_authorized_transport() -> None:
    session_id, consent_id, terminal_id = uuid4(), uuid4(), uuid4()
    document = '{"report_id":"basic-abc123"}'
    pdf = b"%PDF-1.4\nsynthetic\n%%EOF\n"
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        body = json.loads(request.content)
        assert request.url.path == f"/v1/sessions/{session_id}/basic-report-copy"
        assert request.headers["Authorization"] == "Bearer test-token"
        assert request.headers["X-Terminal-ID"] == str(terminal_id)
        assert request.headers["Idempotency-Key"] == "stable-copy-key"
        assert body["document_json"] == document
        assert body["consent_record_id"] == str(consent_id)
        return httpx.Response(201, json={"data": {
            "report_id": body["report_id"], "version": body["version"],
            "document_sha256": body["document_sha256"], "pdf_sha256": body["pdf_sha256"],
        }})

    client = HttpIngestionClient(
        "https://cloud.test", terminal_id=terminal_id,
        transport=httpx.MockTransport(handler),
    )
    try:
        receipt = client.upload_basic_report_copy(
            "test-token", session_id=session_id, report_id="basic-abc123", version=1,
            source="LOCAL_BASIC_COPY", document_json=document, pdf_bytes=pdf,
            document_sha256=hashlib.sha256(document.encode()).hexdigest(),
            pdf_sha256=hashlib.sha256(pdf).hexdigest(), consent_record_id=consent_id,
            idempotency_key="stable-copy-key",
        )
        assert receipt["report_id"] == "basic-abc123"
        assert len(seen) == 1
    finally:
        client.close()


def test_cloud_copy_uses_recovery_consent_only_after_raw_confirmation() -> None:
    original, replacement = uuid4(), uuid4()
    store = object.__new__(StateStore)
    store.sync_handoff_state = lambda _session: "READY_FOR_NETWORK"
    store.subject_recovery_authorization = lambda _session: SimpleNamespace(
        replacement_consent=SimpleNamespace(consent_record_id=replacement),
    )
    store.sync_handoff_envelope = lambda _session: SimpleNamespace(
        consent=SimpleNamespace(consent_record_id=original),
    )
    assert store.report_copy_consent_id("session") is None
    store.sync_handoff_state = lambda _session: "CLOUD_CONFIRMED"
    assert store.report_copy_consent_id("session") == str(replacement)
    store.subject_recovery_authorization = lambda _session: None
    assert store.report_copy_consent_id("session") == str(original)
