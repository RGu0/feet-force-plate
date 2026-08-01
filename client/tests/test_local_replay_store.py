from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from client.app.local_store import LocalReplayStore
from client.local_analysis.models import (
    LocalAnalysisResult,
    LocalMetricValue,
    LocalQualityStatus,
    WithheldMetric,
)
from client.security.key_envelope import (
    DualEnvelopeBlobCodec,
    KeyringTerminalKeyHandle,
    ServerKeyset,
    generate_test_keypair,
)
from client.workflow.consent import ConsentPolicy, ConsentRequest
from client.workflow.participant import (
    AnalysisProfile,
    CreateSubjectRequest,
    ExternalIdType,
    ExternalSubjectIdInput,
    FieldState,
    OptionalField,
)
from client.workflow.participant import SubjectLookupRequest
from client.workflow.models import ScreeningParticipantContext
from client.workflow.protocol import default_standard_protocol


class _MemoryKeyring:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, account: str) -> str | None:
        return self.values.get((service, account))

    def set_password(self, service: str, account: str, value: str) -> None:
        self.values[(service, account)] = value


class _Report:
    report_id = "report-42"
    version = 1
    session_id = "session-42"

    def to_json(self) -> str:
        return '{"subject":"secret-1234","kind":"V1_REPLAY_DEBUG"}'


def test_local_replay_store_writes_encrypted_versioned_local_analysis_result(
    tmp_path: Path,
) -> None:
    keyring = _MemoryKeyring()
    server = generate_test_keypair()
    codec = DualEnvelopeBlobCodec(
        server_keyset=ServerKeyset("replay-dev-no-cloud", server.public_key_pem),
        terminal_key=KeyringTerminalKeyHandle(
            service_name="FeetForcePlate.test",
            account_name="terminal-analysis",
            keyring_backend=keyring,
        ),
    )
    store = LocalReplayStore(tmp_path, codec=codec)
    result = LocalAnalysisResult(
        result_version=1,
        algorithm_version="v1-replay-debug/1.0.0",
        protocol_id="standard-static-bilateral",
        protocol_version="v1-replay-debug/1.0.0",
        source_frame_count=1_658,
        quality_status=LocalQualityStatus.VALID,
        raw_count_heatmap=None,
        relative_heatmap=((0.0, 1.0),),
        customer_metrics=(),
        internal_metrics=(
            LocalMetricValue(
                "BILATERAL_EYES_OPEN:left",
                50.0,
                "percent",
                "v1-replay-debug/1",
            ),
        ),
        withheld_metrics=(
            WithheldMetric(
                "BILATERAL_EYES_OPEN:left",
                "REPLAY_DEBUG_NOT_CUSTOMER_VALIDATED",
            ),
        ),
    )

    store.save_analysis_result("session-42", result)

    encrypted = store.db.execute(
        "SELECT payload FROM replay_analysis_results WHERE session_id=?",
        ("session-42",),
    ).fetchone()[0]
    assert b"standard-static-bilateral" not in encrypted
    restored = __import__("json").loads(
        codec.decrypt(encrypted, context="analysis:session-42")
    )
    assert restored["schema_version"] == "local-analysis-result/1"
    assert restored["result_version"] == 1
    assert restored["algorithm_version"] == "v1-replay-debug/1.0.0"
    assert restored["customer_metrics"] == []
    assert restored["internal_metrics"][0]["key"] == "BILATERAL_EYES_OPEN:left"
    assert (
        restored["withheld_metrics"][0]["reason"]
        == "REPLAY_DEBUG_NOT_CUSTOMER_VALIDATED"
    )


def test_local_replay_report_is_dual_encrypted_and_readable_after_reopen(tmp_path: Path) -> None:
    keyring = _MemoryKeyring()
    server = generate_test_keypair()
    def codec() -> DualEnvelopeBlobCodec:
        return DualEnvelopeBlobCodec(
            server_keyset=ServerKeyset("replay-dev-no-cloud", server.public_key_pem),
            terminal_key=KeyringTerminalKeyHandle(
                service_name="FeetForcePlate.test",
                account_name="terminal-42",
                keyring_backend=keyring,
            ),
        )

    store = LocalReplayStore(tmp_path, codec=codec())
    store.save_report(_Report())
    payload = store.db.execute("SELECT payload FROM replay_reports").fetchone()[0]

    assert b"secret-1234" not in payload
    reopened = LocalReplayStore(tmp_path, codec=codec())
    assert "secret-1234" in reopened.load_report("report-42", 1)


def test_local_replay_store_records_each_completed_stage(tmp_path: Path) -> None:
    keyring = _MemoryKeyring()
    server = generate_test_keypair()
    store = LocalReplayStore(
        tmp_path,
        codec=DualEnvelopeBlobCodec(
            server_keyset=ServerKeyset("replay-dev-no-cloud", server.public_key_pem),
            terminal_key=KeyringTerminalKeyHandle(
                service_name="FeetForcePlate.test",
                account_name="terminal-42",
                keyring_backend=keyring,
            ),
        ),
    )
    store.db.execute("INSERT INTO replay_sessions VALUES (?,?,?,?)", ("session-42", "subject-42", "fixture", "ACQUIRING"))
    store.db.commit()

    store.mark_stage_complete("session-42", "BILATERAL_EYES_OPEN")
    store.mark_stage_complete("session-42", "BILATERAL_EYES_CLOSED")

    assert [row[0] for row in store.db.execute("SELECT stage_id FROM replay_stage_completions ORDER BY completed_at")] == [
        "BILATERAL_EYES_OPEN",
        "BILATERAL_EYES_CLOSED",
    ]


def test_local_replay_store_encrypts_updated_profile_fields(tmp_path: Path) -> None:
    keyring = _MemoryKeyring()
    server = generate_test_keypair()
    codec = DualEnvelopeBlobCodec(
        server_keyset=ServerKeyset("replay-dev-no-cloud", server.public_key_pem),
        terminal_key=KeyringTerminalKeyHandle(
            service_name="FeetForcePlate.test",
            account_name="terminal-profile",
            keyring_backend=keyring,
        ),
    )
    store = LocalReplayStore(tmp_path, codec=codec)
    subject = store.create(
        CreateSubjectRequest(tenant_id="tenant-1", analysis_profile=AnalysisProfile.unknown())
    )
    profile = AnalysisProfile(
        age_band=OptionalField(FieldState.PROVIDED, "60-69"),
        sex=OptionalField(FieldState.PROVIDED, "female"),
    )

    store.update_profile(tenant_id="tenant-1", subject_uuid=subject.subject_uuid, profile=profile)

    encrypted = store.db.execute("SELECT payload FROM subjects WHERE subject_id=?", (subject.subject_uuid,)).fetchone()[0]
    assert b"60-69" not in encrypted
    restored = codec.decrypt(encrypted, context=f"subject:{subject.subject_uuid}")
    assert b'"age_band":{"state":"PROVIDED","value":"60-69"}' in restored


def test_local_identifier_index_is_hmac_and_isolated_by_tenant_issuer_and_type(tmp_path: Path) -> None:
    store = LocalReplayStore(tmp_path, query_index_key=b"q" * 32)
    number = "REC-1001"
    first = store.create(
        CreateSubjectRequest(
            tenant_id="tenant-a",
            analysis_profile=AnalysisProfile.unknown(),
            external_id=ExternalSubjectIdInput("site-a", ExternalIdType.INSTITUTION_RECORD, number),
        )
    )
    second = store.create(
        CreateSubjectRequest(
            tenant_id="tenant-b",
            analysis_profile=AnalysisProfile.unknown(),
            external_id=ExternalSubjectIdInput("site-a", ExternalIdType.INSTITUTION_RECORD, number),
        )
    )

    assert store.resolve(SubjectLookupRequest("tenant-a", "site-a", ExternalIdType.INSTITUTION_RECORD, number)).candidates[0] == first
    assert store.resolve(SubjectLookupRequest("tenant-b", "site-a", ExternalIdType.INSTITUTION_RECORD, number)).candidates[0] == second
    assert store.resolve(SubjectLookupRequest("tenant-a", "site-b", ExternalIdType.INSTITUTION_RECORD, number)).status.value == "NOT_FOUND"
    assert store.resolve(SubjectLookupRequest("tenant-a", "site-a", ExternalIdType.MEDICAL_RECORD_NUMBER, number)).status.value == "NOT_FOUND"
    stored = store.db.execute("SELECT lookup_hmac FROM subject_identifier_index LIMIT 1").fetchone()[0]
    assert stored != __import__("hashlib").sha256(number.encode()).digest()


def test_duplicate_local_identifier_is_not_auto_merged_or_partially_created(
    tmp_path: Path,
) -> None:
    store = LocalReplayStore(tmp_path, query_index_key=b"d" * 32)
    request = CreateSubjectRequest(
        tenant_id="tenant-a",
        analysis_profile=AnalysisProfile.unknown(),
        external_id=ExternalSubjectIdInput(
            "site-a",
            ExternalIdType.INSTITUTION_RECORD,
            "REC-1001",
        ),
    )
    first = store.create(request)

    try:
        store.create(request)
    except RuntimeError as error:
        assert "机构人员" in str(error)
    else:
        raise AssertionError("duplicate identifiers require explicit confirmation")

    assert store.db.execute("SELECT COUNT(*) FROM subjects").fetchone()[0] == 1
    resolution = store.resolve(
        SubjectLookupRequest(
            "tenant-a",
            "site-a",
            ExternalIdType.INSTITUTION_RECORD,
            "REC-1001",
        )
    )
    assert resolution.candidates == (first,)


def test_local_consent_reuse_requires_the_same_tenant_and_policy_scope(
    tmp_path: Path,
) -> None:
    keyring = _MemoryKeyring()
    server = generate_test_keypair()
    store = LocalReplayStore(
        tmp_path,
        codec=DualEnvelopeBlobCodec(
            server_keyset=ServerKeyset("replay-dev-no-cloud", server.public_key_pem),
            terminal_key=KeyringTerminalKeyHandle(
                service_name="FeetForcePlate.test",
                account_name="terminal-consent-scope",
                keyring_backend=keyring,
            ),
        ),
        query_index_key=b"c" * 32,
    )
    subject = store.create(
        CreateSubjectRequest(
            tenant_id="tenant-a",
            analysis_profile=AnalysisProfile.unknown(),
        )
    )
    receipt = store.create_consent(
        ConsentRequest(
            tenant_id="tenant-a",
            terminal_id="terminal-a",
            subject_uuid=subject.subject_uuid,
            policy_version="privacy/1",
            purpose_codes=("SCREENING",),
            data_categories=("PROFILE",),
            evidence_type="OPERATOR_CONFIRMED",
        )
    )

    assert store.find_valid(
        tenant_id="tenant-a",
        subject_uuid=subject.subject_uuid,
        policy=ConsentPolicy("privacy/1", ("SCREENING",), ("PROFILE",)),
    ) == receipt
    assert store.find_valid(
        tenant_id="tenant-b",
        subject_uuid=subject.subject_uuid,
        policy=ConsentPolicy("privacy/1", ("SCREENING",), ("PROFILE",)),
    ) is None
    assert store.find_valid(
        tenant_id="tenant-a",
        subject_uuid=subject.subject_uuid,
        policy=ConsentPolicy("privacy/2", ("SCREENING",), ("PROFILE",)),
    ) is None
    assert store.find_valid(
        tenant_id="tenant-a",
        subject_uuid=subject.subject_uuid,
        policy=ConsentPolicy(
            "privacy/1",
            ("SCREENING",),
            ("PROFILE", "CONTACT"),
        ),
    ) is None


def test_local_consent_reconfirmation_preserves_prior_receipt(
    tmp_path: Path,
) -> None:
    keyring = _MemoryKeyring()
    server = generate_test_keypair()
    store = LocalReplayStore(
        tmp_path,
        codec=DualEnvelopeBlobCodec(
            server_keyset=ServerKeyset("replay-dev-no-cloud", server.public_key_pem),
            terminal_key=KeyringTerminalKeyHandle(
                service_name="FeetForcePlate.test",
                account_name="terminal-consent-history",
                keyring_backend=keyring,
            ),
        ),
        query_index_key=b"h" * 32,
    )
    subject = store.create(
        CreateSubjectRequest(
            tenant_id="tenant-a",
            analysis_profile=AnalysisProfile.unknown(),
        )
    )
    common = {
        "tenant_id": "tenant-a",
        "terminal_id": "terminal-a",
        "subject_uuid": subject.subject_uuid,
        "purpose_codes": ("SCREENING",),
        "evidence_type": "OPERATOR_CONFIRMED",
    }

    first = store.create_consent(
        ConsentRequest(
            policy_version="privacy/1",
            data_categories=("PROFILE",),
            **common,
        )
    )
    second = store.create_consent(
        ConsentRequest(
            policy_version="privacy/2",
            data_categories=("PROFILE", "CONTACT"),
            **common,
        )
    )

    assert first.consent_record_id != second.consent_record_id
    assert store.db.execute("SELECT COUNT(*) FROM consents").fetchone()[0] == 2


def test_local_consent_cannot_be_created_for_a_subject_in_another_tenant(
    tmp_path: Path,
) -> None:
    store = LocalReplayStore(tmp_path, query_index_key=b"t" * 32)
    subject = store.create(
        CreateSubjectRequest(
            tenant_id="tenant-a",
            analysis_profile=AnalysisProfile.unknown(),
        )
    )

    try:
        store.create_consent(
            ConsentRequest(
                tenant_id="tenant-b",
                terminal_id="terminal-b",
                subject_uuid=subject.subject_uuid,
                policy_version="privacy/1",
                purpose_codes=("SCREENING",),
                data_categories=("PROFILE",),
                evidence_type="OPERATOR_CONFIRMED",
            )
        )
    except KeyError:
        pass
    else:
        raise AssertionError("cross-tenant consent creation must be rejected")


def test_legacy_single_consent_is_migrated_without_losing_reuse(
    tmp_path: Path,
) -> None:
    keyring = _MemoryKeyring()
    server = generate_test_keypair()
    codec = DualEnvelopeBlobCodec(
        server_keyset=ServerKeyset("replay-dev-no-cloud", server.public_key_pem),
        terminal_key=KeyringTerminalKeyHandle(
            service_name="FeetForcePlate.test",
            account_name="terminal-consent-migration",
            keyring_backend=keyring,
        ),
    )
    subject_id = "subject-legacy"
    receipt = {
        "consent_record_id": "consent-legacy",
        "tenant_id": "tenant-a",
        "subject_uuid": subject_id,
        "policy_version": "privacy/1",
        "purpose_codes": ["SCREENING"],
        "data_categories": ["PROFILE"],
    }
    db = sqlite3.connect(tmp_path / "local-replay.sqlite3")
    db.execute(
        "CREATE TABLE subjects ("
        "subject_id TEXT PRIMARY KEY, tenant TEXT NOT NULL, payload BLOB NOT NULL)"
    )
    db.execute(
        "INSERT INTO subjects VALUES (?,?,?)",
        (subject_id, "tenant-a", b"legacy-subject-payload"),
    )
    db.execute(
        "CREATE TABLE consents (subject_id TEXT PRIMARY KEY, payload BLOB NOT NULL)"
    )
    db.execute(
        "INSERT INTO consents VALUES (?,?)",
        (
            subject_id,
            codec.encrypt(
                json.dumps(receipt).encode(),
                context=f"consent:{subject_id}",
            ),
        ),
    )
    db.commit()
    db.close()

    store = LocalReplayStore(
        tmp_path,
        codec=codec,
        query_index_key=b"m" * 32,
    )

    restored = store.find_valid(
        tenant_id="tenant-a",
        subject_uuid=subject_id,
        policy=ConsentPolicy("privacy/1", ("SCREENING",), ("PROFILE",)),
    )
    assert restored is not None
    assert restored.consent_record_id == "consent-legacy"
    assert {
        row[1] for row in store.db.execute("PRAGMA table_info(consents)")
    } == {"consent_id", "tenant", "subject_id", "payload"}


def test_unreadable_legacy_consent_is_retained_for_controlled_recovery(
    tmp_path: Path,
) -> None:
    """Catch migration deleting authorization evidence it cannot decrypt."""

    subject_id = "subject-unreadable-legacy"
    database = sqlite3.connect(tmp_path / "local-replay.sqlite3")
    database.execute(
        "CREATE TABLE subjects ("
        "subject_id TEXT PRIMARY KEY, tenant TEXT NOT NULL, payload BLOB NOT NULL)"
    )
    database.execute(
        "INSERT INTO subjects VALUES (?,?,?)",
        (subject_id, "tenant-a", b"legacy-subject-payload"),
    )
    database.execute(
        "CREATE TABLE consents (subject_id TEXT PRIMARY KEY, payload BLOB NOT NULL)"
    )
    database.execute(
        "INSERT INTO consents VALUES (?,?)",
        (subject_id, b"unreadable-encrypted-consent"),
    )
    database.commit()
    database.close()

    store = LocalReplayStore(tmp_path, query_index_key=b"r" * 32)

    tables = {
        row[0]
        for row in store.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    assert "legacy_consents" in tables
    assert store.db.execute("SELECT COUNT(*) FROM legacy_consents").fetchone()[0] == 1
    assert store.db.execute("SELECT COUNT(*) FROM consents").fetchone()[0] == 0


def test_local_subject_access_and_export_append_encrypted_audit_events(
    tmp_path: Path,
) -> None:
    keyring = _MemoryKeyring()
    server = generate_test_keypair()
    codec = DualEnvelopeBlobCodec(
        server_keyset=ServerKeyset("replay-dev-no-cloud", server.public_key_pem),
        terminal_key=KeyringTerminalKeyHandle(
            service_name="FeetForcePlate.test",
            account_name="terminal-audit",
            keyring_backend=keyring,
        ),
    )
    store = LocalReplayStore(
        tmp_path,
        codec=codec,
        query_index_key=b"a" * 32,
    )
    subject = store.create(
        CreateSubjectRequest(
            tenant_id="tenant-a",
            analysis_profile=AnalysisProfile.unknown(),
        )
    )

    store.record_subject_access(
        tenant_id="tenant-a",
        subject_uuid=subject.subject_uuid,
        purpose="SCREENING_SUBJECT_LOOKUP",
    )
    store.record_subject_export(
        tenant_id="tenant-a",
        subject_uuid=subject.subject_uuid,
        report_id="report-1",
        report_version=2,
        purpose="SCREENING_REPORT_EXPORT",
    )

    rows = store.db.execute(
        "SELECT event_id, event_type, payload FROM subject_audit_events "
        "ORDER BY rowid"
    ).fetchall()
    assert [row[1] for row in rows] == ["SUBJECT_ACCESS", "SUBJECT_EXPORT"]
    assert b"SCREENING_SUBJECT_LOOKUP" not in rows[0][2]
    assert b"report-1" not in rows[1][2]
    restored = [
        __import__("json").loads(codec.decrypt(payload, context=f"audit:{event_id}"))
        for event_id, _, payload in rows
    ]
    assert restored == [
        {
            "purpose": "SCREENING_SUBJECT_LOOKUP",
            "schema_version": "subject-audit-event/1",
        },
        {
            "purpose": "SCREENING_REPORT_EXPORT",
            "report_id": "report-1",
            "report_version": 2,
            "schema_version": "subject-audit-event/1",
        },
    ]


def test_local_subject_audit_rejects_cross_tenant_writes(tmp_path: Path) -> None:
    store = LocalReplayStore(tmp_path, query_index_key=b"a" * 32)
    subject = store.create(
        CreateSubjectRequest(
            tenant_id="tenant-a",
            analysis_profile=AnalysisProfile.unknown(),
        )
    )

    try:
        store.record_subject_access(
            tenant_id="tenant-b",
            subject_uuid=subject.subject_uuid,
            purpose="SCREENING_SUBJECT_LOOKUP",
        )
    except KeyError:
        pass
    else:
        raise AssertionError("cross-tenant audit writes must be rejected")

    assert store.db.execute(
        "SELECT COUNT(*) FROM subject_audit_events"
    ).fetchone()[0] == 0


def test_local_replay_session_keeps_encrypted_protocol_and_fixture_provenance(tmp_path: Path) -> None:
    keyring = _MemoryKeyring()
    server = generate_test_keypair()
    codec = DualEnvelopeBlobCodec(
        server_keyset=ServerKeyset("replay-dev-no-cloud", server.public_key_pem),
        terminal_key=KeyringTerminalKeyHandle(
            service_name="FeetForcePlate.test",
            account_name="terminal-session",
            keyring_backend=keyring,
        ),
    )
    store = LocalReplayStore(tmp_path, codec=codec)

    session_id = store.create_session(
        ScreeningParticipantContext("subject-42", "consent-42"),
        default_standard_protocol().snapshot(),
    )

    encrypted = store.db.execute(
        "SELECT payload FROM replay_session_metadata WHERE session_id=?", (session_id,)
    ).fetchone()[0]
    assert b"BILATERAL_EYES_OPEN" not in encrypted
    restored = codec.decrypt(encrypted, context=f"session:{session_id}")
    assert b'"fixture_id":"dop4864_reference_protocol_v1"' in restored
    assert b'"stage_ids":["BILATERAL_EYES_OPEN"' in restored
