from __future__ import annotations

from pathlib import Path

from client.app.local_store import LocalReplayStore
from client.security.key_envelope import (
    DualEnvelopeBlobCodec,
    KeyringTerminalKeyHandle,
    ServerKeyset,
    generate_test_keypair,
)
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
