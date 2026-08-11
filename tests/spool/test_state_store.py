import sqlite3
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import ValidationError

from client.spool.state_store import (
    GateReason,
    SensitiveBlobCodec,
    StateStore,
    ValidSegmentRecord,
)
from shared.contracts.client_sync import FormalUploadEnvelope
from shared.contracts.cloud import (
    ConsentCreateRequest,
    IdentityProfileInput,
    SessionVersions,
    SubjectCreateRequest,
    TestProtocol as UploadTestProtocol,
)


class StaticKeyProvider:
    def __init__(self, key: bytes) -> None:
        self.key = key
        self.calls = 0

    def get_key(self) -> bytes:
        self.calls += 1
        return self.key


def _formal_upload_envelope(
    *,
    session_id: UUID,
    subject_id: UUID,
    consent_id: UUID,
) -> FormalUploadEnvelope:
    return FormalUploadEnvelope(
        session_id=session_id,
        subject=SubjectCreateRequest(
            subject_uuid=subject_id,
            identity_profile=IdentityProfileInput(contact="13800000000"),
        ),
        consent=ConsentCreateRequest(
            consent_record_id=consent_id,
            subject_uuid=subject_id,
            policy_version="consent/1",
            purpose_codes=("SCREENING",),
            data_categories=("SCREENING",),
            granted_at=datetime(2026, 8, 11, tzinfo=UTC),
            evidence_type="OPERATOR_CONFIRMED",
            terminal_signature="test-signature-value",
        ),
        client_installation_id=uuid4(),
        hardware_asset_id=uuid4(),
        site_id=None,
        test_protocol=UploadTestProtocol(id="standard-screening", version="1.0"),
        versions=SessionVersions(
            app="0.1.0",
            protocol_profile="do-p4864/1",
            payload_schema="raw-segment/1",
            calibration="calibration/1",
        ),
        started_at=datetime(2026, 8, 11, tzinfo=UTC),
    )


class StateStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.db_path = Path(self.directory.name) / "state.sqlite3"
        self.keys = StaticKeyProvider(b"k" * 32)
        self.store = StateStore(self.db_path, SensitiveBlobCodec(self.keys))

    def tearDown(self) -> None:
        self.store.close()
        self.directory.cleanup()

    def test_database_uses_wal_and_versioned_migrations(self) -> None:
        self.assertEqual(self.store.journal_mode, "wal")
        self.assertEqual(self.store.synchronous_level, 2)
        self.assertEqual(self.store.busy_timeout_ms, 5_000)
        self.assertEqual(self.store.schema_version, 8)
        expected = {
            "subject_refs",
            "consent_records",
            "sessions",
            "segments",
            "upload_tasks",
            "report_versions",
            "terminal_state",
            "device_validation_runs",
            "telemetry_events",
            "sync_handoffs",
            "session_artifacts",
        }
        self.assertTrue(expected.issubset(self.store.table_names()))

    def test_formal_upload_envelope_rejects_cross_identity_aliases(self) -> None:
        session_id = uuid4()
        subject_id = uuid4()
        consent_id = uuid4()
        valid = _formal_upload_envelope(
            session_id=session_id,
            subject_id=subject_id,
            consent_id=consent_id,
        )

        with self.subTest("consent subject"):
            with self.assertRaisesRegex(
                ValidationError, "consent subject must match upload subject"
            ):
                FormalUploadEnvelope(
                    **{
                        **valid.model_dump(),
                        "consent": valid.consent.model_copy(
                            update={"subject_uuid": uuid4()}
                        ),
                    }
                )
        with self.subTest("session subject alias"):
            with self.assertRaisesRegex(
                ValidationError, "session id cannot alias subject uuid"
            ):
                FormalUploadEnvelope(
                    **{**valid.model_dump(), "session_id": subject_id}
                )

    def test_valid_session_atomically_persists_an_encrypted_upload_envelope(self) -> None:
        session_id = uuid4()
        subject_id = uuid4()
        consent_id = uuid4()
        envelope = _formal_upload_envelope(
            session_id=session_id,
            subject_id=subject_id,
            consent_id=consent_id,
        )
        self.store.put_subject_ref(str(subject_id), b"opaque")
        self.store.put_consent_record(
            str(consent_id), str(subject_id), b"operator-confirmed", recorded_at_ns=1
        )

        self.store.commit_valid_session(
            str(session_id),
            subject_uuid=str(subject_id),
            consent_id=str(consent_id),
            versions_json=b'{"protocol":"static-balance/1"}',
            started_at_ns=10,
            ended_at_ns=20,
            manifest_sha256="a" * 64,
            segments=(
                ValidSegmentRecord(
                    segment_id="formal-segment-1",
                    relative_path="sessions/formal/segment-1.ffps",
                    byte_count=128,
                    sealed_at_ns=20,
                ),
            ),
            upload_envelope=envelope,
        )

        self.assertEqual(self.store.sync_handoff_envelope(str(session_id)), envelope)
        self.assertNotIn(b"13800000000", self.db_path.read_bytes())

    def test_upload_envelope_identity_mismatch_registers_no_transaction_rows(self) -> None:
        envelope_session_id = uuid4()
        envelope_subject_id = uuid4()
        envelope_consent_id = uuid4()
        envelope = _formal_upload_envelope(
            session_id=envelope_session_id,
            subject_id=envelope_subject_id,
            consent_id=envelope_consent_id,
        )
        cases = (
            ("session", uuid4(), envelope_subject_id, envelope_consent_id),
            ("subject", envelope_session_id, uuid4(), envelope_consent_id),
            ("consent", envelope_session_id, envelope_subject_id, uuid4()),
        )
        for label, session_id, subject_id, consent_id in cases:
            segment_id = f"mismatch-{label}"
            with self.subTest(label):
                with self.assertRaisesRegex(ValueError, "upload envelope .* mismatch"):
                    self.store.commit_valid_session(
                        str(session_id),
                        subject_uuid=str(subject_id),
                        consent_id=str(consent_id),
                        versions_json=b"{}",
                        started_at_ns=10,
                        ended_at_ns=20,
                        manifest_sha256="b" * 64,
                        segments=(
                            ValidSegmentRecord(
                                segment_id=segment_id,
                                relative_path=f"sessions/{session_id}/segment.ffps",
                                byte_count=128,
                                sealed_at_ns=20,
                            ),
                        ),
                        upload_envelope=envelope,
                    )
                with self.assertRaises(KeyError):
                    self.store.session_status(str(session_id))
                self.assertFalse(self.store.segment_exists(segment_id))
                with self.assertRaises(KeyError):
                    self.store.sync_handoff_state(str(session_id))

    def test_sensitive_subject_and_consent_blobs_are_encrypted_outside_database_key(self) -> None:
        subject_plaintext = b'internal-subject-ref:person@example.invalid'
        consent_plaintext = b'{"consent":true,"operator":"private"}'
        self.store.put_subject_ref("subject-uuid", subject_plaintext)
        self.store.put_consent_record(
            "consent-1", "subject-uuid", consent_plaintext, recorded_at_ns=10
        )

        database_bytes = self.db_path.read_bytes()
        self.assertNotIn(subject_plaintext, database_bytes)
        self.assertNotIn(consent_plaintext, database_bytes)
        self.assertNotIn(self.keys.key, database_bytes)
        self.assertEqual(
            self.store.get_subject_ref("subject-uuid"), subject_plaintext
        )
        self.assertEqual(
            self.store.get_consent_record("consent-1"), consent_plaintext
        )
        self.assertGreaterEqual(self.keys.calls, 4)

    def test_sensitive_reference_updates_preserve_existing_session_foreign_keys(self) -> None:
        self.store.put_subject_ref("subject-uuid", b"old-ref")
        self.store.put_consent_record(
            "consent-1", "subject-uuid", b"old-consent", recorded_at_ns=10
        )
        self.store.create_session(
            "session-1",
            subject_uuid="subject-uuid",
            consent_id="consent-1",
            lifecycle_status="CLOSED",
            versions_json=b"{}",
            started_at_ns=20,
        )

        self.store.put_subject_ref("subject-uuid", b"new-ref")
        self.store.put_consent_record(
            "consent-1", "subject-uuid", b"new-consent", recorded_at_ns=30
        )

        self.assertEqual(self.store.get_subject_ref("subject-uuid"), b"new-ref")
        self.assertEqual(self.store.get_consent_record("consent-1"), b"new-consent")
        self.assertEqual(self.store.session_status("session-1")[0], "CLOSED")

    def test_ready_session_handoff_encrypts_supporting_local_analysis(self) -> None:
        self.store.put_subject_ref("subject-uuid", b"opaque")
        self.store.commit_valid_session(
            "session-1",
            subject_uuid="subject-uuid",
            consent_id=None,
            versions_json=b'{"protocol":"static-balance/1"}',
            started_at_ns=10,
            ended_at_ns=20,
            manifest_sha256="a" * 64,
            segments=(
                ValidSegmentRecord(
                    segment_id="segment-1",
                    relative_path="sessions/session-1/segment-1.ffps",
                    byte_count=128,
                    sealed_at_ns=20,
                ),
            ),
        )
        payload = (
            b'{"authority":"SUPPORTING_NON_AUTHORITATIVE",'
            b'"cloud_recompute_from_raw":true}'
        )

        self.store.attach_supporting_local_analysis("session-1", payload)

        self.assertEqual(self.store.sync_handoff_state("session-1"), "READY_FOR_NETWORK")
        self.assertEqual(self.store.supporting_local_analysis("session-1"), payload)
        self.assertNotIn(payload, self.db_path.read_bytes())

    def test_schema_five_database_upgrades_to_encrypted_analysis_handoff(self) -> None:
        self.store.close()
        connection = sqlite3.connect(self.db_path)
        try:
            columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(sync_handoffs)")
            }
            if "supporting_local_analysis" in columns:
                connection.execute(
                    "ALTER TABLE sync_handoffs DROP COLUMN supporting_local_analysis"
                )
            connection.execute("PRAGMA user_version=5")
            connection.commit()
        finally:
            connection.close()

        self.store = StateStore(self.db_path, SensitiveBlobCodec(self.keys))

        self.assertEqual(self.store.schema_version, 8)
        with sqlite3.connect(self.db_path) as verification:
            columns = {
                row[1]
                for row in verification.execute("PRAGMA table_info(sync_handoffs)")
            }
        self.assertIn("supporting_local_analysis", columns)
        self.assertIn("upload_envelope", columns)

    def test_recovery_marks_acquiring_incomplete_and_requeues_uploading(self) -> None:
        self.store.put_subject_ref("subject-uuid", b"opaque")
        self.store.create_session(
            "session-1",
            subject_uuid="subject-uuid",
            consent_id=None,
            lifecycle_status="ACQUIRING",
            versions_json=b"{}",
            started_at_ns=20,
        )
        self.store.add_segment(
            "segment-1",
            session_id="session-1",
            relative_path="session-1/segment-1.ffps",
            byte_count=500,
            state="SEALED",
            sealed_at_ns=30,
        )
        self.store.add_upload_task("upload-1", "segment-1", state="UPLOADING")

        result = self.store.recover_interrupted_state(recovered_at_ns=40)

        self.assertEqual(result.sessions_marked_incomplete, 1)
        self.assertEqual(result.uploads_requeued, 1)
        session = self.store.session_status("session-1")
        self.assertEqual(session, ("CLOSED", "INCOMPLETE", 40))
        self.assertEqual(self.store.upload_state("upload-1"), "PENDING")

    def test_transactional_offline_snapshot_and_all_new_test_gates(self) -> None:
        now = 100 * 60 * 60 * 1_000_000_000
        self.store.record_successful_online(now - 25 * 60 * 60 * 1_000_000_000)
        self.store.put_subject_ref("subject-uuid", b"opaque")
        for index in range(50):
            session_id = f"session-{index}"
            segment_id = f"segment-{index}"
            self.store.create_session(
                session_id,
                subject_uuid="subject-uuid",
                consent_id=None,
                lifecycle_status="CLOSED",
                versions_json=b"{}",
                started_at_ns=index,
            )
            self.store.add_segment(
                segment_id,
                session_id=session_id,
                relative_path=f"{session_id}/{segment_id}.ffps",
                byte_count=50_000_000,
                state="PENDING_UPLOAD",
                sealed_at_ns=index,
            )
        snapshot = self.store.offline_snapshot()
        decision = self.store.evaluate_new_test(
            now_ns=now,
            free_disk_bytes=5,
            estimated_test_bytes=10,
            reserve_bytes=1,
        )

        self.assertEqual(snapshot.pending_session_count, 50)
        self.assertEqual(snapshot.pending_bytes, 2_500_000_000)
        self.assertEqual(
            set(decision.reasons),
            {
                GateReason.OFFLINE_TOO_LONG,
                GateReason.PENDING_SESSION_LIMIT,
                GateReason.PENDING_BYTE_LIMIT,
                GateReason.INSUFFICIENT_DISK,
            },
        )
        self.assertFalse(decision.allow_new_test)
        self.assertTrue(decision.allow_current_test_finalize)
        self.assertTrue(decision.allow_existing_report_view)
        self.assertTrue(decision.allow_upload)

    def test_acknowledgement_never_creates_an_automatic_cleanup_candidate(self) -> None:
        self.store.put_subject_ref("subject-uuid", b"opaque")
        self.store.create_session(
            "session-1",
            subject_uuid="subject-uuid",
            consent_id=None,
            lifecycle_status="CLOSED",
            versions_json=b"{}",
            started_at_ns=1,
        )
        for segment_id, state, retain_until in (
            ("pending", "PENDING_UPLOAD", 1),
            ("retained", "ACKNOWLEDGED", 200),
            ("eligible", "ACKNOWLEDGED", 50),
        ):
            self.store.add_segment(
                segment_id,
                session_id="session-1",
                relative_path=f"session-1/{segment_id}.ffps",
                byte_count=10,
                state=state,
                sealed_at_ns=1,
                acknowledged_at_ns=2 if state == "ACKNOWLEDGED" else None,
                retain_until_ns=retain_until,
            )

        self.assertEqual(self.store.cleanup_candidates(now_ns=100), [])
        with self.assertRaisesRegex(RuntimeError, "automatic segment cleanup"):
            self.store.finalize_segment_cleanup("eligible", now_ns=100)
        self.assertTrue(self.store.segment_exists("eligible"))
        self.assertTrue(self.store.segment_exists("pending"))
        self.assertTrue(self.store.segment_exists("retained"))

    def test_corrupt_quarantined_data_still_counts_against_offline_quota(self) -> None:
        self.store.put_subject_ref("subject-uuid", b"opaque")
        self.store.create_session(
            "session-1",
            subject_uuid="subject-uuid",
            consent_id=None,
            lifecycle_status="CLOSED",
            versions_json=b"{}",
            started_at_ns=1,
        )
        self.store.add_segment(
            "corrupt-1",
            session_id="session-1",
            relative_path="session-1/corrupt-1.ffps.corrupt",
            byte_count=123,
            state="CORRUPT",
            sealed_at_ns=1,
        )

        snapshot = self.store.offline_snapshot()

        self.assertEqual(snapshot.pending_session_count, 1)
        self.assertEqual(snapshot.pending_bytes, 123)


if __name__ == "__main__":
    unittest.main()
