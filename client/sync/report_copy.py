"""Restart-safe local BASIC report handoff, separate from raw capture."""

from __future__ import annotations

from enum import StrEnum
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
from typing import Protocol
from uuid import UUID

from client.reporting.models import BasicReportDocument
from client.spool.state_store import KeyProvider, SensitiveBlobCodec
from client.sync.persistent_upload import (
    UploadAuthenticationRequired, UploadBlocked, UploadConflict, UploadRetryable,
)


class ReportCopyOutcome(StrEnum):
    IDLE = "IDLE"
    CONFIRMED = "CONFIRMED"
    DEFERRED = "DEFERRED"
    CONFLICT = "CONFLICT"
    BLOCKED = "BLOCKED"


class _CloudBinding(Protocol):
    def report_copy_consent_id(self, session_id: str) -> str | None: ...


class _ReportRenderer(Protocol):
    def render(self, report: BasicReportDocument, destination: Path) -> None: ...


class ReportCopyUploader:
    """Uses its own SQLite connection so the UI connection stays thread-owned."""

    def __init__(
        self, database_path: Path, key_provider: KeyProvider, physical_store: _CloudBinding,
        cloud, renderer: _ReportRenderer, *, now_ns=time.time_ns,
    ) -> None:
        self._db = sqlite3.connect(database_path, timeout=5.0, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA busy_timeout=5000")
        self._codec = SensitiveBlobCodec(key_provider)
        self._physical = physical_store
        self._cloud = cloud
        self._renderer = renderer
        self._now_ns = now_ns
        self._lock = threading.RLock()
        with self._lock, self._db:
            self._db.execute(
                "UPDATE institution_report_copy_handoffs SET state='PENDING' WHERE state='UPLOADING'"
            )

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def run_once(self, tokens) -> ReportCopyOutcome:
        now = self._now_ns()
        with self._lock:
            candidates = self._db.execute(
                """SELECT session_id FROM institution_report_copy_handoffs
                   WHERE state='PENDING' OR (state='RETRY_WAIT' AND next_attempt_at_ns<=?)
                   ORDER BY rowid""",
                (now,),
            ).fetchall()
        for candidate in candidates:
            session_id = str(candidate[0])
            consent_id = self._physical.report_copy_consent_id(session_id)
            if consent_id is None:
                continue
            with self._lock, self._db:
                changed = self._db.execute(
                    """UPDATE institution_report_copy_handoffs
                       SET state='UPLOADING', attempt_count=attempt_count+1
                       WHERE session_id=? AND state IN ('PENDING','RETRY_WAIT')""",
                    (session_id,),
                ).rowcount
            if changed:
                return self._upload(session_id, consent_id, tokens)
        return ReportCopyOutcome.IDLE

    def _upload(self, session_id: str, consent_id: str, tokens) -> ReportCopyOutcome:
        try:
            row = self._row(session_id)
            report_id = self._codec.decrypt(
                bytes(row["report_id"]), context=f"report_copy_id:{session_id}",
            ).decode("ascii")
            document = self._codec.decrypt(
                bytes(row["payload"]), context=f"report:{report_id}:{row['version']}",
            )
            if hashlib.sha256(document).hexdigest() != row["document_sha256"]:
                raise UploadConflict("local report document digest changed")
            report = BasicReportDocument.from_json(document.decode("utf-8"))
            if report.session_id != session_id or report.report_id != report_id:
                raise UploadConflict("local report binding changed")
            pdf = self._pdf_for(row, report)
            payload = dict(
                session_id=UUID(session_id), report_id=report_id, version=int(row["version"]),
                source="LOCAL_BASIC_COPY", document_json=document.decode("utf-8"),
                pdf_bytes=pdf, document_sha256=row["document_sha256"],
                pdf_sha256=hashlib.sha256(pdf).hexdigest(), consent_record_id=UUID(consent_id),
                idempotency_key=row["idempotency_key"],
            )
            try:
                receipt = self._cloud.upload_basic_report_copy(tokens.current_access_token(), **payload)
            except UploadAuthenticationRequired:
                tokens.refresh()
                receipt = self._cloud.upload_basic_report_copy(tokens.current_access_token(), **payload)
            if any(receipt.get(key) != payload[key] for key in (
                "report_id", "version", "document_sha256", "pdf_sha256",
            )):
                raise UploadConflict("cloud report copy receipt mismatch")
            receipt_sha = hashlib.sha256(json.dumps(
                receipt, sort_keys=True, separators=(",", ":"),
            ).encode("utf-8")).hexdigest()
            self._transition(session_id, "CONFIRMED", receipt_sha=receipt_sha)
            return ReportCopyOutcome.CONFIRMED
        except UploadConflict:
            self._transition(session_id, "CONFLICT")
            return ReportCopyOutcome.CONFLICT
        except UploadBlocked:
            self._transition(session_id, "BLOCKED")
            return ReportCopyOutcome.BLOCKED
        except UploadRetryable as exc:
            self._defer(session_id, exc.retry_after_seconds)
            return ReportCopyOutcome.DEFERRED
        except Exception:
            self._defer(session_id, None)
            return ReportCopyOutcome.DEFERRED

    def _row(self, session_id: str) -> sqlite3.Row:
        with self._lock:
            row = self._db.execute(
                """SELECT handoff.*, report.payload FROM institution_report_copy_handoffs handoff
                   JOIN institution_reports report USING(report_lookup)
                   WHERE handoff.session_id=? AND handoff.state='UPLOADING'""",
                (session_id,),
            ).fetchone()
        if row is None:
            raise UploadConflict("local report copy handoff missing")
        return row

    def _pdf_for(self, row: sqlite3.Row, report: BasicReportDocument) -> bytes:
        session_id = row["session_id"]
        if row["pdf_payload"] is not None:
            pdf = self._codec.decrypt(
                bytes(row["pdf_payload"]), context=f"report_copy_pdf:{session_id}",
            )
            if hashlib.sha256(pdf).hexdigest() != row["pdf_sha256"]:
                raise UploadConflict("local report PDF digest changed")
            return pdf
        with tempfile.TemporaryDirectory(prefix="feetforceplate-report-copy-") as directory:
            destination = Path(directory) / "copy.pdf"
            self._renderer.render(report, destination)
            pdf = destination.read_bytes()
        if not pdf.startswith(b"%PDF-") or b"%%EOF" not in pdf[-1024:] or len(pdf) > 8 * 1024 * 1024:
            raise UploadConflict("local report PDF is invalid")
        encrypted = self._codec.encrypt(pdf, context=f"report_copy_pdf:{session_id}")
        with self._lock, self._db:
            self._db.execute(
                """UPDATE institution_report_copy_handoffs SET pdf_payload=?, pdf_sha256=?
                   WHERE session_id=? AND state='UPLOADING'""",
                (encrypted, hashlib.sha256(pdf).hexdigest(), session_id),
            )
        return pdf

    def _transition(self, session_id: str, state: str, *, receipt_sha: str | None = None) -> None:
        with self._lock, self._db:
            self._db.execute(
                """UPDATE institution_report_copy_handoffs
                   SET state=?, next_attempt_at_ns=NULL, receipt_sha256=?
                   WHERE session_id=? AND state='UPLOADING'""",
                (state, receipt_sha, session_id),
            )

    def _defer(self, session_id: str, retry_after_seconds: float | None) -> None:
        with self._lock, self._db:
            row = self._db.execute(
                "SELECT attempt_count FROM institution_report_copy_handoffs WHERE session_id=?",
                (session_id,),
            ).fetchone()
            attempts = int(row[0]) if row else 1
            delay = min(900.0, 5.0 * (2 ** min(attempts - 1, 8)))
            if retry_after_seconds is not None:
                delay = max(delay, retry_after_seconds)
            self._db.execute(
                """UPDATE institution_report_copy_handoffs
                   SET state='RETRY_WAIT', next_attempt_at_ns=?
                   WHERE session_id=? AND state='UPLOADING'""",
                (self._now_ns() + int(delay * 1_000_000_000), session_id),
            )
