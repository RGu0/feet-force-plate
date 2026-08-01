"""Small dual-encrypted SQLite store used only by the local replay runtime."""
from __future__ import annotations
import base64
import hmac
import json
import os
import sqlite3
import uuid
from dataclasses import asdict
from pathlib import Path
from platformdirs import user_data_path
from client.security.key_envelope import (
    DualEnvelopeBlobCodec,
    KeyringTerminalKeyHandle,
    ServerKeyset,
    generate_test_keypair,
)
from client.local_analysis.models import LocalAnalysisResult
from client.workflow.consent import ConsentReceipt
from client.workflow.participant import SubjectResolution, SubjectResolutionStatus, SubjectSummary
from client.app.ui_models import DashboardSnapshot, ScreeningRecordRow, SupportSnapshot
from datetime import datetime

class LocalReplayStore:
    """Local replay storage; not an institution-production identity store.

    Legacy replay databases are migrated to a composite HMAC index when their
    encrypted payload can be opened.  Entries whose old payload cannot be
    opened are retained but deliberately become unresolvable; recreating an
    identifier is safer than guessing its tenant/issuer/type context.
    """

    _QUERY_KEY_SERVICE = "FeetForcePlate.local-replay.query-index"
    _QUERY_KEY_ACCOUNT = "hmac-sha256-v1"

    def __init__(
        self,
        root: Path | None = None,
        *,
        codec: DualEnvelopeBlobCodec | None = None,
        query_index_key: bytes | None = None,
    ):
        self.root = root or Path(user_data_path("FeetForcePlate", "TechFlex", ensure_exists=True))
        self.root.mkdir(parents=True, exist_ok=True)
        self.codec = codec or _local_replay_development_codec()
        self.db = sqlite3.connect(self.root / "local-replay.sqlite3")
        self._query_index_key = query_index_key or _load_local_query_index_key()
        self._migrate_subject_index()
        self._migrate_consent_store()
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS subject_audit_events ("
            "event_id TEXT PRIMARY KEY, tenant TEXT NOT NULL, "
            "subject_id TEXT NOT NULL, event_type TEXT NOT NULL, "
            "created_at TEXT NOT NULL, payload BLOB NOT NULL, "
            "FOREIGN KEY(subject_id) REFERENCES subjects(subject_id))"
        )
        self.db.execute("CREATE TABLE IF NOT EXISTS replay_sessions (session_id TEXT PRIMARY KEY, subject_id TEXT, fixture_sha TEXT, status TEXT)")
        self.db.execute("CREATE TABLE IF NOT EXISTS replay_session_metadata (session_id TEXT PRIMARY KEY, payload BLOB NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS replay_analysis_results (session_id TEXT PRIMARY KEY, payload BLOB NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS replay_stage_completions (session_id TEXT NOT NULL, stage_id TEXT NOT NULL, completed_at TEXT NOT NULL, PRIMARY KEY(session_id, stage_id))")
        self.db.execute("CREATE TABLE IF NOT EXISTS replay_reports (report_id TEXT, version INTEGER, session_id TEXT, payload BLOB NOT NULL, PRIMARY KEY(report_id,version))")
        self.db.commit()

    def _migrate_consent_store(self) -> None:
        columns = {row[1] for row in self.db.execute("PRAGMA table_info(consents)")}
        if columns and "consent_id" not in columns:
            self.db.execute("ALTER TABLE consents RENAME TO legacy_consents")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS consents ("
            "consent_id TEXT PRIMARY KEY, tenant TEXT NOT NULL, "
            "subject_id TEXT NOT NULL, payload BLOB NOT NULL, "
            "FOREIGN KEY(subject_id) REFERENCES subjects(subject_id))"
        )
        if columns and "consent_id" not in columns:
            migration_failed = False
            for subject_id, payload in self.db.execute(
                "SELECT subject_id, payload FROM legacy_consents"
            ):
                try:
                    restored = json.loads(
                        self.codec.decrypt(payload, context=f"consent:{subject_id}")
                    )
                    self.db.execute(
                        "INSERT OR IGNORE INTO consents VALUES (?,?,?,?)",
                        (
                            restored["consent_record_id"],
                            restored["tenant_id"],
                            subject_id,
                            payload,
                        ),
                    )
                except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                    migration_failed = True
                    continue
            if not migration_failed:
                self.db.execute("DROP TABLE legacy_consents")
        self.db.execute(
            "CREATE INDEX IF NOT EXISTS consent_subject_scope "
            "ON consents(tenant, subject_id)"
        )
        self.db.commit()
    def _migrate_subject_index(self) -> None:
        columns = {row[1] for row in self.db.execute("PRAGMA table_info(subjects)")}
        if "lookup" in columns:
            self.db.execute("ALTER TABLE subjects RENAME TO legacy_subjects")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS subjects (subject_id TEXT PRIMARY KEY, tenant TEXT NOT NULL, payload BLOB NOT NULL)"
        )
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS subject_identifier_index (tenant TEXT NOT NULL, issuer TEXT NOT NULL, id_type TEXT NOT NULL, lookup_hmac BLOB NOT NULL, subject_id TEXT NOT NULL UNIQUE, PRIMARY KEY(tenant, issuer, id_type, lookup_hmac), FOREIGN KEY(subject_id) REFERENCES subjects(subject_id))"
        )
        if "lookup" in columns:
            for _lookup, subject_id, tenant, payload in self.db.execute(
                "SELECT lookup, subject_id, tenant, payload FROM legacy_subjects"
            ):
                self.db.execute(
                    "INSERT OR IGNORE INTO subjects(subject_id, tenant, payload) VALUES (?,?,?)",
                    (subject_id, tenant, payload),
                )
                try:
                    external_id = json.loads(
                        self.codec.decrypt(payload, context=f"subject:{subject_id}")
                    ).get("external_id")
                except (TypeError, ValueError, json.JSONDecodeError):
                    external_id = None
                if external_id:
                    self.db.execute(
                        "INSERT OR IGNORE INTO subject_identifier_index VALUES (?,?,?,?,?)",
                        (tenant, "legacy-local", "institution_record", self._lookup(tenant, "legacy-local", "institution_record", external_id), subject_id),
                    )
            self.db.execute("DROP TABLE legacy_subjects")
        self.db.commit()

    def _lookup(self, tenant_id, issuer, id_type, value):
        normalized = value.strip()
        context = "\x1f".join((tenant_id, issuer, str(getattr(id_type, "value", id_type)), normalized))
        return hmac.digest(self._query_index_key, context.encode("utf-8"), "sha256")

    def resolve(self, request):
        row=self.db.execute(
            "SELECT subjects.subject_id, subjects.tenant FROM subject_identifier_index JOIN subjects USING(subject_id) WHERE subject_identifier_index.tenant=? AND issuer=? AND id_type=? AND lookup_hmac=?",
            (request.tenant_id, request.issuer, request.id_type.value, self._lookup(request.tenant_id, request.issuer, request.id_type, request.external_id)),
        ).fetchone()
        return SubjectResolution(SubjectResolutionStatus.FOUND,(SubjectSummary(row[0],row[1],f"**{request.external_id[-4:]}"),)) if row else SubjectResolution(SubjectResolutionStatus.NOT_FOUND)
    def create(self, request):
        value=request.external_id.external_id if request.external_id else f"anonymous-{uuid.uuid4().hex}"
        subject=SubjectSummary(uuid.uuid4().hex,request.tenant_id,f"**{value[-4:]}")
        payload=self.codec.encrypt(json.dumps({
            "external_id": value,
            "analysis_profile": _profile_payload(request.analysis_profile),
            "identity": None if request.identity is None else {
                "name": request.identity.name,
                "contact": request.identity.contact,
                "government_id": request.identity.government_id,
            },
        }, sort_keys=True, separators=(",", ":")).encode(),context=f"subject:{subject.subject_uuid}")
        try:
            with self.db:
                self.db.execute(
                    "INSERT INTO subjects VALUES (?,?,?)",
                    (subject.subject_uuid, subject.tenant_id, payload),
                )
                if request.external_id is not None:
                    self.db.execute(
                        "INSERT INTO subject_identifier_index VALUES (?,?,?,?,?)",
                        (
                            subject.tenant_id,
                            request.external_id.issuer,
                            request.external_id.id_type.value,
                            self._lookup(
                                subject.tenant_id,
                                request.external_id.issuer,
                                request.external_id.id_type,
                                value,
                            ),
                            subject.subject_uuid,
                        ),
                    )
        except sqlite3.IntegrityError as exc:
            raise RuntimeError(
                "机构编号存在档案冲突，不能自动合并，请由机构人员确认"
            ) from exc
        return subject
    def update_profile(self, *, tenant_id, subject_uuid, profile):
        row = self.db.execute(
            "SELECT tenant,payload FROM subjects WHERE subject_id=?", (subject_uuid,)
        ).fetchone()
        if row is None or row[0] != tenant_id:
            raise KeyError("subject is unavailable in this tenant")
        payload = json.loads(self.codec.decrypt(row[1], context=f"subject:{subject_uuid}"))
        payload["analysis_profile"] = _profile_payload(profile)
        encrypted = self.codec.encrypt(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(),
            context=f"subject:{subject_uuid}",
        )
        self.db.execute("UPDATE subjects SET payload=? WHERE subject_id=?", (encrypted, subject_uuid))
        self.db.commit()
    def find_valid(self, *, tenant_id, subject_uuid, policy):
        rows = self.db.execute(
            "SELECT payload FROM consents "
            "WHERE tenant=? AND subject_id=? ORDER BY rowid DESC",
            (tenant_id, subject_uuid),
        ).fetchall()
        for row in rows:
            value = json.loads(
                self.codec.decrypt(row[0], context=f"consent:{subject_uuid}")
            )
            value["purpose_codes"] = tuple(value["purpose_codes"])
            value["data_categories"] = tuple(value["data_categories"])
            receipt = ConsentReceipt(**value)
            if (
                receipt.policy_version == policy.policy_version
                and policy.accepts_purpose_codes(receipt.purpose_codes)
                and receipt.data_categories == policy.data_categories
            ):
                return receipt
        return None

    def create_consent(self, request):
        subject = self.db.execute(
            "SELECT tenant FROM subjects WHERE subject_id=?",
            (request.subject_uuid,),
        ).fetchone()
        if subject is None or subject[0] != request.tenant_id:
            raise KeyError("subject is unavailable in this tenant")
        receipt=ConsentReceipt(uuid.uuid4().hex,request.tenant_id,request.subject_uuid,request.policy_version,request.purpose_codes,request.data_categories)
        payload=self.codec.encrypt(json.dumps({"consent_record_id":receipt.consent_record_id,"tenant_id":receipt.tenant_id,"subject_uuid":receipt.subject_uuid,"policy_version":receipt.policy_version,"purpose_codes":receipt.purpose_codes,"data_categories":receipt.data_categories}).encode(),context=f"consent:{receipt.subject_uuid}")
        self.db.execute(
            "INSERT INTO consents VALUES (?,?,?,?)",
            (receipt.consent_record_id, receipt.tenant_id, receipt.subject_uuid, payload),
        )
        self.db.commit();return receipt

    def record_subject_access(self, *, tenant_id, subject_uuid, purpose):
        self._record_subject_audit(
            tenant_id=tenant_id,
            subject_uuid=subject_uuid,
            event_type="SUBJECT_ACCESS",
            details={"purpose": purpose},
        )

    def record_subject_export(
        self,
        *,
        tenant_id,
        subject_uuid,
        report_id,
        report_version,
        purpose,
    ):
        self._record_subject_audit(
            tenant_id=tenant_id,
            subject_uuid=subject_uuid,
            event_type="SUBJECT_EXPORT",
            details={
                "purpose": purpose,
                "report_id": report_id,
                "report_version": report_version,
            },
        )

    def _record_subject_audit(
        self,
        *,
        tenant_id,
        subject_uuid,
        event_type,
        details,
    ):
        subject = self.db.execute(
            "SELECT tenant FROM subjects WHERE subject_id=?",
            (subject_uuid,),
        ).fetchone()
        if subject is None or subject[0] != tenant_id:
            raise KeyError("subject is unavailable in this tenant")
        event_id = uuid.uuid4().hex
        payload = self.codec.encrypt(
            json.dumps(
                {
                    "schema_version": "subject-audit-event/1",
                    **details,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode(),
            context=f"audit:{event_id}",
        )
        self.db.execute(
            "INSERT INTO subject_audit_events VALUES (?,?,?,?,?,?)",
            (
                event_id,
                tenant_id,
                subject_uuid,
                event_type,
                datetime.now().isoformat(),
                payload,
            ),
        )
        self.db.commit()
    def create_session(self, context, protocol):
        session_id=uuid.uuid4().hex
        fixture_sha = "2495b910bbf7e4fcca0cd0db36dde809f0fd6395bb6060eded44db575acd6f90"
        metadata = self.codec.encrypt(
            json.dumps(
                {
                    "fixture_id": "dop4864_reference_protocol_v1",
                    "fixture_sha256": fixture_sha,
                    "protocol": asdict(protocol),
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode(),
            context=f"session:{session_id}",
        )
        self.db.execute("INSERT INTO replay_sessions VALUES (?,?,?,?)",(session_id,context.subject_uuid,fixture_sha,"ACQUIRING"))
        self.db.execute("INSERT INTO replay_session_metadata VALUES (?,?)", (session_id, metadata))
        self.db.commit()
        return session_id
    def mark_incomplete(self, session_id):
        self.db.execute("UPDATE replay_sessions SET status='INCOMPLETE' WHERE session_id=?",(session_id,));self.db.commit()
    def mark_stage_complete(self, session_id: str, stage_id: str) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO replay_stage_completions VALUES (?,?,?)",
            (session_id, stage_id, datetime.now().isoformat()),
        )
        self.db.commit()
    def finalize(self, session_id):
        self.db.execute("UPDATE replay_sessions SET status='CLOSED' WHERE session_id=?",(session_id,));self.db.commit()
    def save_analysis_result(
        self,
        session_id: str,
        result: LocalAnalysisResult,
    ) -> None:
        serialized = asdict(result)
        serialized.update(
            {
                "schema_version": "local-analysis-result/1",
                "data_completeness": "FOUR_STAGES_COMPLETE",
            }
        )
        payload = self.codec.encrypt(
            json.dumps(
                serialized,
                sort_keys=True,
                separators=(",", ":"),
            ).encode(),
            context=f"analysis:{session_id}",
        )
        self.db.execute("INSERT OR REPLACE INTO replay_analysis_results VALUES (?,?)", (session_id, payload))
        self.db.commit()
    def save_report(self, report):
        payload=self.codec.encrypt(report.to_json().encode(),context=f"report:{report.report_id}:{report.version}")
        self.db.execute("INSERT OR REPLACE INTO replay_reports VALUES (?,?,?,?)",(report.report_id,report.version,report.session_id,payload));self.db.commit()
    def load_report(self, report_id: str, version: int) -> str:
        row = self.db.execute("SELECT payload FROM replay_reports WHERE report_id=? AND version=?", (report_id, version)).fetchone()
        if row is None: raise KeyError(f"unknown report {report_id} v{version}")
        return self.codec.decrypt(row[0], context=f"report:{report_id}:{version}").decode("utf-8")
    def recent_records(self, *, query=""):
        rows = self.db.execute(
            """
            SELECT sessions.session_id, sessions.status, reports.report_id,
                   reports.version, MAX(stages.completed_at)
            FROM replay_sessions AS sessions
            LEFT JOIN replay_reports AS reports ON reports.session_id = sessions.session_id
            LEFT JOIN replay_stage_completions AS stages ON stages.session_id = sessions.session_id
            GROUP BY sessions.session_id, sessions.status, reports.report_id, reports.version
            ORDER BY sessions.rowid DESC
            """
        ).fetchall()
        return tuple(
            ScreeningRecordRow(
                "回放调试",
                (completed_at or datetime.now().isoformat())[5:16].replace("T", " "),
                "四段 V1 回放",
                "调试报告" if status == "CLOSED" and report_id else status,
                report_id=report_id,
                report_version=version,
            )
            for _, status, report_id, version, completed_at in rows
            if query in "回放调试"
        )
    def dashboard_snapshot(self):
        records=self.recent_records(); return DashboardSnapshot("本地 V1 回放调试终端", "回放数据源已校验", "仅本地，不上传", f"本地记录：{len(records)} 次", records)
    def support_snapshot(self): return SupportSnapshot("回放 fixture 已校验", "未连接云端", f"本地记录：{len(self.recent_records())} 次", "v1-replay-debug")


def _local_replay_development_codec() -> DualEnvelopeBlobCodec:
    """Explicit local-only fallback until License validation supplies a signed keyset."""

    server = generate_test_keypair()
    return DualEnvelopeBlobCodec(
        server_keyset=ServerKeyset("replay-dev-no-cloud", server.public_key_pem),
        terminal_key=KeyringTerminalKeyHandle(
            service_name="FeetForcePlate.local-replay",
            account_name="terminal-p256",
        ),
    )


def _load_local_query_index_key() -> bytes:
    """Load a stable local secret from the OS credential vault, never SQLite."""

    try:
        import keyring
    except ImportError as exc:  # pragma: no cover - packaging contract
        raise RuntimeError("system credential storage is required for replay lookup") from exc
    encoded = keyring.get_password(
        LocalReplayStore._QUERY_KEY_SERVICE,
        LocalReplayStore._QUERY_KEY_ACCOUNT,
    )
    if encoded is None:
        key = os.urandom(32)
        keyring.set_password(
            LocalReplayStore._QUERY_KEY_SERVICE,
            LocalReplayStore._QUERY_KEY_ACCOUNT,
            base64.b64encode(key).decode("ascii"),
        )
        return key
    return base64.b64decode(encoded.encode("ascii"), validate=True)


def _profile_payload(profile) -> dict[str, dict[str, object | None]]:
    values: dict[str, dict[str, object | None]] = {}
    for name in ("age_band", "sex", "height_cm", "weight_kg", "condition_tags", "injury_tags"):
        field = getattr(profile, name)
        value = field.value
        values[name] = {
            "state": field.state.value,
            "value": list(value) if isinstance(value, tuple) else value,
        }
    return values
