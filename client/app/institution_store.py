"""Encrypted local persistence for the authenticated institution runtime.

This deliberately has no replay fixtures, generated server key, or replay table
names.  It is the small local boundary used while an institution session is
collecting and waiting for the cloud handoff.
"""

from __future__ import annotations

import base64
from dataclasses import asdict
from datetime import UTC, datetime
import hmac
import json
import os
from pathlib import Path
import sqlite3
import uuid
from collections.abc import Callable

from platformdirs import user_data_path

from client.reporting.models import BasicReportDocument
from client.spool.state_store import (
    KeyProvider,
    KeyProviderUnavailable,
    SensitiveBlobCodec,
)
from client.workflow.consent import (
    ConsentEvidenceSigner,
    ConsentPolicy,
    ConsentReceipt,
    ConsentRequest,
)
from client.workflow.participant import (
    AnalysisProfile,
    CreateSubjectRequest,
    SubjectLookupRequest,
    SubjectResolution,
    SubjectResolutionStatus,
    SubjectSummary,
)
from client.workflow.protocol import ProtocolSnapshot
from client.workflow.models import ScreeningParticipantContext
from shared.contracts.client_sync import canonical_json_bytes
from shared.contracts.cloud import (
    ConsentCreateRequest,
    ExternalIdentifierInput,
    IdentityProfileInput,
    ProfileValue,
    SubjectCreateRequest,
)


class KeyringAesKeyProvider:
    """Keeps the AES-256 data key in the OS credential vault, never SQLite."""

    _SERVICE = "FeetForcePlate.institution-storage"
    _ACCOUNT = "aes256-v1"

    def get_key(self) -> bytes:
        try:
            import keyring
        except ImportError as exc:  # pragma: no cover - packaging contract
            raise KeyProviderUnavailable("system credential storage is required") from exc
        try:
            encoded = keyring.get_password(self._SERVICE, self._ACCOUNT)
        except Exception as exc:
            raise KeyProviderUnavailable(
                "system credential storage is temporarily unavailable"
            ) from exc
        if encoded is None:
            key = os.urandom(32)
            try:
                keyring.set_password(
                    self._SERVICE, self._ACCOUNT, base64.b64encode(key).decode()
                )
            except Exception as exc:
                raise KeyProviderUnavailable(
                    "system credential storage is temporarily unavailable"
                ) from exc
            return key
        try:
            key = base64.b64decode(encoded.encode("ascii"), validate=True)
        except (UnicodeEncodeError, ValueError) as exc:
            raise ValueError("stored institution data key is malformed") from exc
        if len(key) != 32:
            raise ValueError("stored institution data key is not AES-256")
        return key


class KeyringConsentEvidenceSigner:
    _SERVICE = "FeetForcePlate.institution-storage"
    _ACCOUNT = "consent-evidence-hmac-sha256-v1"

    def sign(
        self,
        request: ConsentRequest,
        *,
        consent_record_id: str,
        granted_at: datetime,
    ) -> str:
        payload = canonical_json_bytes({
            "consent_record_id": consent_record_id,
            "tenant_id": request.tenant_id,
            "terminal_id": request.terminal_id,
            "subject_uuid": request.subject_uuid,
            "policy_version": request.policy_version,
            "purpose_codes": request.purpose_codes,
            "data_categories": request.data_categories,
            "evidence_type": request.evidence_type,
            "granted_at": granted_at,
        })
        return "hmac-sha256:" + base64.urlsafe_b64encode(
            hmac.digest(self._key(), payload, "sha256")
        ).rstrip(b"=").decode("ascii")

    def _key(self) -> bytes:
        try:
            import keyring
        except ImportError as exc:  # pragma: no cover - packaging contract
            raise RuntimeError("system credential storage is required") from exc
        encoded = keyring.get_password(self._SERVICE, self._ACCOUNT)
        if encoded is None:
            key = os.urandom(32)
            keyring.set_password(self._SERVICE, self._ACCOUNT, base64.b64encode(key).decode())
            return key
        key = base64.b64decode(encoded.encode("ascii"), validate=True)
        if len(key) != 32:
            raise RuntimeError("stored consent evidence key is not SHA-256 sized")
        return key


class InstitutionLocalStore:
    """Tenant-scoped local state encrypted with a Keychain-backed AES key."""

    _QUERY_KEY_SERVICE = "FeetForcePlate.institution-storage"
    _QUERY_KEY_ACCOUNT = "hmac-sha256-v1"

    def __init__(
        self,
        root: Path,
        *,
        key_provider: KeyProvider,
        query_index_key: bytes,
        now: Callable[[], datetime],
        consent_signer: ConsentEvidenceSigner,
    ) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "institution.sqlite3"
        self.db = sqlite3.connect(self.path)
        self.codec = SensitiveBlobCodec(key_provider)
        if len(query_index_key) != 32:
            raise ValueError("institution query index key must be 32 bytes")
        self._query_index_key = query_index_key
        self._now = now
        self._consent_signer = consent_signer
        self._create_schema()

    @classmethod
    def open(
        cls,
        root: str | Path | None = None,
        *,
        key_provider: KeyProvider | None = None,
        query_index_key: bytes | None = None,
        now: Callable[[], datetime] | None = None,
        consent_signer: ConsentEvidenceSigner | None = None,
    ) -> "InstitutionLocalStore":
        storage_root = Path(root) if root is not None else Path(
            user_data_path("FeetForcePlate", "TechFlex", ensure_exists=True)
        )
        return cls(
            storage_root,
            key_provider=key_provider or KeyringAesKeyProvider(),
            query_index_key=query_index_key or _load_query_index_key(),
            now=now or _utc_now,
            consent_signer=consent_signer or KeyringConsentEvidenceSigner(),
        )

    def close(self) -> None:
        self.db.close()

    def consent_port(self) -> _InstitutionConsentPort:
        return _InstitutionConsentPort(self)

    def _create_schema(self) -> None:
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS institution_subjects (
                subject_uuid TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                issuer TEXT,
                id_type TEXT,
                lookup_hmac BLOB,
                payload BLOB NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS institution_subject_lookup
                ON institution_subjects(tenant_id, issuer, id_type, lookup_hmac);
            CREATE TABLE IF NOT EXISTS institution_consents (
                consent_lookup BLOB PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                subject_uuid TEXT NOT NULL REFERENCES institution_subjects(subject_uuid),
                payload BLOB NOT NULL
            );
            CREATE TABLE IF NOT EXISTS institution_sessions (
                session_id TEXT PRIMARY KEY,
                subject_uuid TEXT NOT NULL REFERENCES institution_subjects(subject_uuid),
                lifecycle_status TEXT NOT NULL,
                payload BLOB NOT NULL
            );
            CREATE TABLE IF NOT EXISTS institution_stage_completions (
                session_id TEXT NOT NULL REFERENCES institution_sessions(session_id),
                stage_id TEXT NOT NULL,
                completed_at TEXT NOT NULL,
                PRIMARY KEY (session_id, stage_id)
            );
            CREATE TABLE IF NOT EXISTS institution_reports (
                report_lookup BLOB PRIMARY KEY,
                payload BLOB NOT NULL
            );
            CREATE TABLE IF NOT EXISTS institution_subject_audit (
                event_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                subject_uuid TEXT NOT NULL REFERENCES institution_subjects(subject_uuid),
                event_type TEXT NOT NULL,
                created_at TEXT NOT NULL,
                payload BLOB NOT NULL
            );
            """
        )
        self.db.commit()

    def schema_names(self) -> set[str]:
        return {
            row[0]
            for row in self.db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'institution_%'"
            )
        }

    def _lookup(self, *parts: str) -> bytes:
        return hmac.digest(self._query_index_key, "\x1f".join(parts).encode(), "sha256")

    def _subject_lookup(self, request: SubjectLookupRequest) -> bytes:
        return self._lookup(
            request.tenant_id,
            request.issuer,
            request.id_type.value,
            request.external_id.strip(),
        )

    def resolve(self, request: SubjectLookupRequest) -> SubjectResolution:
        row = self.db.execute(
            """SELECT subject_uuid FROM institution_subjects
               WHERE tenant_id=? AND issuer=? AND id_type=? AND lookup_hmac=?""",
            (request.tenant_id, request.issuer, request.id_type.value, self._subject_lookup(request)),
        ).fetchone()
        if row is None:
            return SubjectResolution(SubjectResolutionStatus.NOT_FOUND)
        return SubjectResolution(
            SubjectResolutionStatus.FOUND,
            (SubjectSummary(row[0], request.tenant_id, _mask(request.external_id)),),
        )

    def create(self, request: CreateSubjectRequest) -> SubjectSummary:
        subject_uuid = uuid.uuid4().hex
        external = request.external_id
        payload = {
            "external_id": external.external_id if external else None,
            "analysis_profile": _profile_payload(request.analysis_profile),
            "identity": None if request.identity is None else asdict(request.identity),
        }
        encrypted = self.codec.encrypt(_json(payload), context=f"subject:{subject_uuid}")
        try:
            with self.db:
                self.db.execute(
                    """INSERT INTO institution_subjects
                    (subject_uuid, tenant_id, issuer, id_type, lookup_hmac, payload)
                    VALUES (?,?,?,?,?,?)""",
                    (
                        subject_uuid,
                        request.tenant_id,
                        external.issuer if external else None,
                        external.id_type.value if external else None,
                        self._lookup(
                            request.tenant_id,
                            external.issuer,
                            external.id_type.value,
                            external.external_id.strip(),
                        ) if external else None,
                        encrypted,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise RuntimeError("机构编号存在档案冲突，不能自动合并，请由机构人员确认") from exc
        return SubjectSummary(
            subject_uuid,
            request.tenant_id,
            _mask(external.external_id) if external else None,
        )

    def update_profile(
        self, *, tenant_id: str, subject_uuid: str, profile: AnalysisProfile
    ) -> None:
        row = self.db.execute(
            "SELECT tenant_id, payload FROM institution_subjects WHERE subject_uuid=?", (subject_uuid,)
        ).fetchone()
        if row is None or row[0] != tenant_id:
            raise KeyError("subject is unavailable in this tenant")
        payload = json.loads(self.codec.decrypt(row[1], context=f"subject:{subject_uuid}"))
        payload["analysis_profile"] = _profile_payload(profile)
        with self.db:
            self.db.execute(
                "UPDATE institution_subjects SET payload=? WHERE subject_uuid=?",
                (self.codec.encrypt(_json(payload), context=f"subject:{subject_uuid}"), subject_uuid),
            )

    def find_valid(
        self, *, tenant_id: str, subject_uuid: str, policy: ConsentPolicy
    ) -> ConsentReceipt | None:
        rows = self.db.execute(
            "SELECT payload FROM institution_consents WHERE tenant_id=? AND subject_uuid=?",
            (tenant_id, subject_uuid),
        ).fetchall()
        for (encrypted,) in rows:
            value = json.loads(self.codec.decrypt(encrypted, context=f"consent:{subject_uuid}"))
            if not all(
                name in value
                for name in ("granted_at", "evidence_type", "terminal_signature")
            ):
                continue
            receipt = ConsentReceipt(
                consent_record_id=value["consent_record_id"], tenant_id=value["tenant_id"],
                subject_uuid=value["subject_uuid"], policy_version=value["policy_version"],
                purpose_codes=tuple(value["purpose_codes"]), data_categories=tuple(value["data_categories"]),
            )
            if (
                receipt.policy_version == policy.policy_version
                and policy.accepts_purpose_codes(receipt.purpose_codes)
                and receipt.data_categories == policy.data_categories
            ):
                return receipt
        return None

    def create_consent(self, request: ConsentRequest) -> ConsentReceipt:
        self._require_subject(request.tenant_id, request.subject_uuid)
        granted_at = self._now()
        receipt = ConsentReceipt(
            consent_record_id=uuid.uuid4().hex, tenant_id=request.tenant_id,
            subject_uuid=request.subject_uuid, policy_version=request.policy_version,
            purpose_codes=request.purpose_codes, data_categories=request.data_categories,
        )
        payload = {
            **asdict(receipt),
            "granted_at": granted_at.isoformat(),
            "evidence_type": request.evidence_type,
            "terminal_signature": self._consent_signer.sign(
                request,
                consent_record_id=receipt.consent_record_id,
                granted_at=granted_at,
            ),
        }
        with self.db:
            self.db.execute(
                "INSERT INTO institution_consents VALUES (?,?,?,?)",
                (
                    self._lookup("consent", receipt.consent_record_id),
                    receipt.tenant_id,
                    receipt.subject_uuid,
                    self.codec.encrypt(_json(payload), context=f"consent:{receipt.subject_uuid}"),
                ),
            )
        return receipt

    def subject_upload_request(self, subject_uuid: str) -> SubjectCreateRequest:
        row = self.db.execute(
            """SELECT tenant_id, issuer, id_type, payload FROM institution_subjects
               WHERE subject_uuid=?""",
            (subject_uuid,),
        ).fetchone()
        if row is None:
            raise KeyError("subject is unavailable for upload")
        tenant_id, issuer, id_type, encrypted = row
        self._require_subject(tenant_id, subject_uuid)
        payload = json.loads(self.codec.decrypt(encrypted, context=f"subject:{subject_uuid}"))
        external_identifier = _external_identifier_upload_request(
            issuer=issuer,
            id_type=id_type,
            external_id=payload["external_id"],
        )
        identity = payload["identity"]
        identity_profile = None
        if identity is not None and (identity.get("name") is not None or identity.get("contact") is not None):
            identity_profile = IdentityProfileInput(
                display_name=identity.get("name"),
                contact=identity.get("contact"),
            )
        return SubjectCreateRequest(
            subject_uuid=subject_uuid,
            external_identifier=external_identifier,
            identity_profile=identity_profile,
            analysis_profile={
                name: ProfileValue(state=value["state"], value=value["value"])
                for name, value in payload["analysis_profile"].items()
            },
        )

    def consent_upload_request(self, consent_record_id: str) -> ConsentCreateRequest:
        row = self.db.execute(
            """SELECT tenant_id, subject_uuid, payload FROM institution_consents
               WHERE consent_lookup=?""",
            (self._lookup("consent", consent_record_id),),
        ).fetchone()
        if row is None:
            raise KeyError("consent is unavailable for upload")
        tenant_id, subject_uuid, encrypted = row
        value = json.loads(self.codec.decrypt(encrypted, context=f"consent:{subject_uuid}"))
        if (
            value.get("consent_record_id") != consent_record_id
            or value.get("tenant_id") != tenant_id
            or value.get("subject_uuid") != subject_uuid
        ):
            raise KeyError("consent identity does not match its stored record")
        self._require_subject(tenant_id, subject_uuid)
        try:
            granted_at = value["granted_at"]
            evidence_type = value["evidence_type"]
            terminal_signature = value["terminal_signature"]
        except KeyError as exc:
            raise KeyError("consent requires operator reconfirmation before upload") from exc
        return ConsentCreateRequest(
            consent_record_id=consent_record_id,
            subject_uuid=subject_uuid,
            policy_version=value["policy_version"],
            purpose_codes=tuple(value["purpose_codes"]),
            data_categories=tuple(value["data_categories"]),
            granted_at=granted_at,
            evidence_type=evidence_type,
            terminal_signature=terminal_signature,
        )

    def create_session(
        self, context: ScreeningParticipantContext, protocol: ProtocolSnapshot
    ) -> str:
        session_id = uuid.uuid4().hex
        payload = self.codec.encrypt(
            _json({"consent_record_id": context.consent_record_id, "protocol": asdict(protocol)}),
            context=f"session:{session_id}",
        )
        with self.db:
            self.db.execute(
                "INSERT INTO institution_sessions VALUES (?,?,?,?)",
                (session_id, context.subject_uuid, "ACQUIRING", payload),
            )
        return session_id

    def mark_incomplete(self, session_id: str) -> None:
        self._set_session_status(session_id, "INCOMPLETE")

    def mark_stage_complete(self, session_id: str, stage_id: str) -> None:
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO institution_stage_completions VALUES (?,?,?)",
                (session_id, stage_id, datetime.now(UTC).isoformat()),
            )

    def finalize(self, session_id: str) -> None:
        self._set_session_status(session_id, "CLOSED")

    def session_status(self, session_id: str) -> str:
        row = self.db.execute(
            "SELECT lifecycle_status FROM institution_sessions WHERE session_id=?", (session_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown institution session {session_id}")
        return row[0]

    def _set_session_status(self, session_id: str, status: str) -> None:
        with self.db:
            cursor = self.db.execute(
                "UPDATE institution_sessions SET lifecycle_status=? WHERE session_id=?", (status, session_id)
            )
        if cursor.rowcount != 1:
            raise KeyError(f"unknown institution session {session_id}")

    def save_report(self, report: BasicReportDocument) -> None:
        context = f"report:{report.report_id}:{report.version}"
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO institution_reports VALUES (?,?)",
                (
                    self._lookup("report", report.report_id, str(report.version)),
                    self.codec.encrypt(report.to_json().encode("utf-8"), context=context),
                ),
            )

    def load_report(self, report_id: str, version: int) -> str:
        row = self.db.execute(
            "SELECT payload FROM institution_reports WHERE report_lookup=?",
            (self._lookup("report", report_id, str(version)),),
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown report {report_id} v{version}")
        return self.codec.decrypt(row[0], context=f"report:{report_id}:{version}").decode("utf-8")

    def record_subject_access(self, *, tenant_id: str, subject_uuid: str, purpose: str) -> None:
        self._record_audit(tenant_id, subject_uuid, "SUBJECT_ACCESS", {"purpose": purpose})

    def record_subject_export(
        self, *, tenant_id: str, subject_uuid: str, report_id: str, report_version: int, purpose: str
    ) -> None:
        self._record_audit(
            tenant_id, subject_uuid, "SUBJECT_EXPORT",
            {"purpose": purpose, "report_id": report_id, "report_version": report_version},
        )

    def _record_audit(
        self, tenant_id: str, subject_uuid: str, event_type: str, details: dict[str, object]
    ) -> None:
        self._require_subject(tenant_id, subject_uuid)
        event_id = uuid.uuid4().hex
        with self.db:
            self.db.execute(
                "INSERT INTO institution_subject_audit VALUES (?,?,?,?,?,?)",
                (event_id, tenant_id, subject_uuid, event_type, datetime.now(UTC).isoformat(),
                 self.codec.encrypt(_json(details), context=f"audit:{event_id}")),
            )

    def _require_subject(self, tenant_id: str, subject_uuid: str) -> None:
        row = self.db.execute(
            "SELECT tenant_id FROM institution_subjects WHERE subject_uuid=?", (subject_uuid,)
        ).fetchone()
        if row is None or row[0] != tenant_id:
            raise KeyError("subject is unavailable in this tenant")


class _InstitutionConsentPort:
    def __init__(self, store: InstitutionLocalStore) -> None:
        self._store = store

    def find_valid(
        self,
        *,
        tenant_id: str,
        subject_uuid: str,
        policy: ConsentPolicy,
    ) -> ConsentReceipt | None:
        return self._store.find_valid(
            tenant_id=tenant_id,
            subject_uuid=subject_uuid,
            policy=policy,
        )

    def create(self, request: ConsentRequest) -> ConsentReceipt:
        return self._store.create_consent(request)


def _load_query_index_key() -> bytes:
    try:
        import keyring
    except ImportError as exc:  # pragma: no cover - packaging contract
        raise RuntimeError("system credential storage is required") from exc
    encoded = keyring.get_password(
        InstitutionLocalStore._QUERY_KEY_SERVICE, InstitutionLocalStore._QUERY_KEY_ACCOUNT
    )
    if encoded is None:
        key = os.urandom(32)
        keyring.set_password(
            InstitutionLocalStore._QUERY_KEY_SERVICE, InstitutionLocalStore._QUERY_KEY_ACCOUNT,
            base64.b64encode(key).decode("ascii"),
        )
        return key
    key = base64.b64decode(encoded.encode("ascii"), validate=True)
    if len(key) != 32:
        raise RuntimeError("stored institution query key is not SHA-256 sized")
    return key


def _profile_payload(profile: AnalysisProfile) -> dict[str, dict[str, object | None]]:
    return {
        name: {"state": field.state.value, "value": field.value}
        for name, field in (
            ("age_band", profile.age_band), ("sex", profile.sex),
            ("height_cm", profile.height_cm), ("weight_kg", profile.weight_kg),
            ("condition_tags", profile.condition_tags), ("injury_tags", profile.injury_tags),
        )
    }


def _external_identifier_upload_request(
    *, issuer: str | None, id_type: str | None, external_id: str | None
) -> ExternalIdentifierInput | None:
    if issuer is None and id_type is None and external_id is None:
        return None
    if issuer is None or id_type is None or external_id is None:
        raise KeyError("subject external identifier does not match its stored record")
    return ExternalIdentifierInput(issuer=issuer, id_type=id_type, external_id=external_id)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=list).encode("utf-8")


def _mask(value: str) -> str:
    return f"**{value[-4:]}" if value else "**"
