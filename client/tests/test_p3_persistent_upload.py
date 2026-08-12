from __future__ import annotations

from datetime import UTC, datetime
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import UUID, uuid4

import httpx
import numpy as np

from client.device.protocol import RawFrame
from client.spool.segments import ImmutableSegmentWriter, SealedSegment
from client.spool.state_store import SensitiveBlobCodec, StateStore, ValidSegmentRecord
from client.sync.persistent_upload import (
    HttpIngestionClient,
    PersistentUploadQueue,
    UploadAuthenticationRequired,
    UploadBlocked,
    UploadConflict,
    UploadCycleOutcome,
    UploadRetryable,
)
from shared.contracts.client_sync import FormalUploadEnvelope, canonical_sha256
from shared.contracts.cloud import (
    ConsentCreateRequest,
    ConsentResponse,
    IngestStatus,
    ManifestCompletionResponse,
    ManifestSegment,
    SegmentAcknowledgement,
    SegmentListResponse,
    SegmentMetadata,
    SegmentReceiptStatus,
    SessionCreateRequest,
    SessionCreateResponse,
    SessionManifest,
    SessionStatusResponse,
    SessionVersions,
    SubjectCreateRequest,
    SubjectSummary,
    TestProtocol as CloudTestProtocol,
    ValidityStatus,
)


class _Key:
    def get_key(self) -> bytes:
        return b"p" * 32


def _frame(source_index: int, monotonic_ns: int) -> RawFrame:
    values = np.full((48, 64), source_index % 255, dtype=np.uint8)
    values.setflags(write=False)
    return RawFrame(
        values=values,
        host_monotonic_ns=monotonic_ns,
        host_wall_time_ns=1_000_000_000 + monotonic_ns,
        source_index=source_index,
        device_frame_seq=None,
        device_timestamp_ns=None,
        quality_flags=frozenset(),
    )


class _IngestionService:
    """In-memory server boundary; each accepted payload is retained by digest."""

    def __init__(self) -> None:
        self.received: dict[int, tuple[SegmentMetadata, bytes]] = {}
        self.manifests: list[SessionManifest] = []
        self.status: SessionStatusResponse | None = None
        self.calls: list[str] = []
        self.subject_keys: list[str] = []
        self.consent_keys: list[str] = []
        self.session_keys: list[str] = []
        self.session_requests: list[SessionCreateRequest] = []
        self.put_calls: list[int] = []
        self.complete_keys: list[str] = []
        self.failures: dict[str, list[Exception]] = {}
        self.lose_complete_response_once = False
        self.list_response: SegmentListResponse | None = None
        self.acknowledgement: SegmentAcknowledgement | None = None
        self.completion_response: ManifestCompletionResponse | None = None
        self.completion_status: SessionStatusResponse | None = None

    def _fail_if_requested(self, operation: str) -> None:
        failures = self.failures.get(operation, [])
        if failures:
            raise failures.pop(0)

    def get_status(
        self, access_token: str, session_id: UUID
    ) -> SessionStatusResponse | None:
        self.calls.append(f"status:{access_token}")
        self._fail_if_requested("status")
        return self.status

    def create_subject(
        self,
        _access_token: str,
        request: SubjectCreateRequest,
        idempotency_key: str,
    ) -> SubjectSummary:
        self.calls.append("subject")
        self.subject_keys.append(idempotency_key)
        self._fail_if_requested("subject")
        return SubjectSummary(
            subject_uuid=request.subject_uuid,
            analysis_profile=request.analysis_profile,
        )

    def create_consent(
        self,
        _access_token: str,
        request: ConsentCreateRequest,
        idempotency_key: str,
    ) -> ConsentResponse:
        self.calls.append("consent")
        self.consent_keys.append(idempotency_key)
        self._fail_if_requested("consent")
        return ConsentResponse(
            consent_record_id=request.consent_record_id,
            subject_uuid=request.subject_uuid,
            policy_version=request.policy_version,
            granted_at=request.granted_at,
        )

    def create_session(
        self,
        _access_token: str,
        request: SessionCreateRequest,
        idempotency_key: str,
    ) -> SessionCreateResponse:
        self.calls.append("session")
        self.session_keys.append(idempotency_key)
        self.session_requests.append(request)
        self._fail_if_requested("session")
        self.status = SessionStatusResponse(
            session_id=request.session_id,
            validity_status=ValidityStatus.UNKNOWN,
            ingest_status=IngestStatus.RECEIVING,
        )
        return SessionCreateResponse(
            session_id=request.session_id,
            ingest_status=IngestStatus.RECEIVING,
        )

    def list_segments(
        self, _access_token: str, session_id: UUID
    ) -> SegmentListResponse:
        self.calls.append("segments")
        self._fail_if_requested("segments")
        if self.list_response is not None:
            return self.list_response
        return SegmentListResponse(
            session_id=session_id,
            received=tuple(
                {
                    "index": index,
                    "sha256": metadata.sha256,
                    "status": SegmentReceiptStatus.ACKNOWLEDGED,
                }
                for index, (metadata, _payload) in sorted(self.received.items())
            ),
            missing=(),
        )

    def put_segment(
        self,
        _access_token: str,
        session_id: UUID,
        metadata: SegmentMetadata,
        payload: bytes,
    ) -> SegmentAcknowledgement:
        self.calls.append("put")
        self.put_calls.append(metadata.segment_index)
        self._fail_if_requested("put")
        self.received[metadata.segment_index] = (metadata, payload)
        if self.acknowledgement is not None:
            return self.acknowledgement
        return SegmentAcknowledgement(
            session_id=session_id,
            index=metadata.segment_index,
            sha256=metadata.sha256,
            status=SegmentReceiptStatus.ACKNOWLEDGED,
            object_key=f"objects/{metadata.segment_index}",
        )

    def complete_session(
        self,
        _access_token: str,
        session_id: UUID,
        manifest: SessionManifest,
        idempotency_key: str,
    ) -> ManifestCompletionResponse:
        self.calls.append("complete")
        self.complete_keys.append(idempotency_key)
        self._fail_if_requested("complete")
        self.manifests.append(manifest)
        for segment in manifest.segments:
            metadata, payload = self.received[segment.index]
            if (metadata.sha256, metadata.size_bytes) != (
                segment.sha256,
                segment.size_bytes,
            ) or payload != self.received[segment.index][1]:
                raise AssertionError("manifest does not describe received immutable bytes")
        result = self.completion_response or ManifestCompletionResponse(
            session_id=session_id,
            ingest_status=IngestStatus.INGESTED,
            manifest_sha256=canonical_sha256(manifest),
        )
        self.status = self.completion_status or SessionStatusResponse(
            session_id=session_id,
            validity_status=ValidityStatus.VALID,
            ingest_status=IngestStatus.INGESTED,
        )
        if self.lose_complete_response_once:
            self.lose_complete_response_once = False
            raise UploadRetryable("completion response lost")
        return result


class _Tokens:
    def __init__(self) -> None:
        self.token = "first-access-token"
        self.current_calls = 0
        self.refresh_calls = 0

    def current_access_token(self) -> str:
        self.current_calls += 1
        return self.token

    def refresh(self) -> object:
        self.refresh_calls += 1
        self.token = "refreshed-access-token"
        return object()


class _Clock:
    def __init__(self, now_ns: int = 1_000_000_000) -> None:
        self.value = now_ns

    def __call__(self) -> int:
        return self.value


class PersistentUploadQueueTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.keys = _Key()
        self.store = StateStore(
            self.root / "state.sqlite3", SensitiveBlobCodec(self.keys)
        )
        self.session_id = uuid4()
        self.subject_id = uuid4()
        self.consent_id = uuid4()
        self.envelope = FormalUploadEnvelope(
            session_id=self.session_id,
            subject=SubjectCreateRequest(subject_uuid=self.subject_id),
            consent=ConsentCreateRequest(
                consent_record_id=self.consent_id,
                subject_uuid=self.subject_id,
                policy_version="privacy-policy/1",
                purpose_codes=("SCREENING_SERVICE",),
                data_categories=("PRESSURE_RAW",),
                granted_at=datetime.fromtimestamp(0, UTC),
                evidence_type="OPERATOR_CONFIRMED",
                terminal_signature="signed-terminal-evidence",
            ),
            site_id=None,
            client_installation_id=uuid4(),
            hardware_asset_id=uuid4(),
            test_protocol=CloudTestProtocol(id="standard-screening", version="1.0"),
            versions=SessionVersions(
                app="0.1.0",
                protocol_profile="do-p4864/1",
                payload_schema="raw-segment/1",
                calibration="calibration/1",
            ),
            config_snapshot={},
            started_at=datetime.fromtimestamp(0, UTC),
        )
        self.store.put_subject_ref(str(self.subject_id), b"opaque")
        self.store.put_consent_record(
            str(self.consent_id),
            str(self.subject_id),
            b"operator-confirmed",
            recorded_at_ns=0,
        )

    def tearDown(self) -> None:
        self.store.close()
        self.directory.cleanup()

    def _seal(self, index: int) -> SealedSegment:
        start = index * 10_000_000_000
        writer = ImmutableSegmentWriter(
            self.root / "sessions",
            session_id=str(self.session_id),
            key_provider=self.keys,
            versions={"payload_schema": "raw-segment/1"},
            segment_duration_seconds=5.0,
            starting_segment_index=index,
        )
        writer.append(_frame(index * 2, start))
        sealed = writer.append(_frame(index * 2 + 1, start + 5_000_000_000))
        assert sealed is not None
        return sealed

    def _commit(self, *sealed: SealedSegment) -> None:
        self.store.commit_valid_session(
            str(self.session_id),
            subject_uuid=str(self.subject_id),
            consent_id=str(self.consent_id),
            versions_json=b"{}",
            started_at_ns=0,
            ended_at_ns=20_000_000_000,
            manifest_sha256="b" * 64,
            upload_envelope=self.envelope,
            segments=tuple(
                ValidSegmentRecord(
                    segment_id=item.segment_id,
                    relative_path=str(item.path.relative_to(self.root)),
                    byte_count=item.byte_count,
                    sealed_at_ns=item.first_source_index,
                )
                for item in sealed
            ),
        )

    def _queue(
        self,
        remote: _IngestionService,
        *,
        clock: _Clock | None = None,
        random_fraction=lambda: 0.0,
    ) -> PersistentUploadQueue:
        return PersistentUploadQueue(
            self.store,
            self.root,
            self.keys,
            remote,
            now_ns=clock or _Clock(),
            random_fraction=random_fraction,
        )

    def test_restart_resumes_only_missing_segments_and_retains_acknowledged_files(
        self,
    ) -> None:
        first, second = self._seal(0), self._seal(1)
        self._commit(first, second)
        remote = _IngestionService()
        first_payload = first.path.read_bytes()
        remote.received[0] = (
            SegmentMetadata(
                segment_index=0,
                start_frame_index=0,
                frame_count=2,
                start_monotonic_ns=0,
                end_monotonic_ns=5_000_000_000,
                compression="none",
                cipher="aes-256-gcm",
                size_bytes=len(first_payload),
                sha256=hashlib.sha256(first_payload).hexdigest(),
                payload_schema_version="raw-segment/1",
            ),
            first_payload,
        )

        outcome = self._queue(remote).upload_next(_Tokens())

        self.assertIs(outcome, UploadCycleOutcome.CONFIRMED)
        self.assertEqual(set(remote.received), {0, 1})
        self.assertEqual(remote.received[1][1], second.path.read_bytes())
        self.assertEqual(
            self.store.sync_handoff_state(str(self.session_id)), "CLOUD_CONFIRMED"
        )
        self.assertTrue(first.path.exists())
        self.assertTrue(second.path.exists())
        self.assertEqual(len(remote.manifests), 1)
        self.assertEqual(remote.session_requests, [self.envelope.session_request()])
        self.assertEqual(
            remote.manifests[0].segments,
            (
                ManifestSegment(
                    index=0,
                    sha256=hashlib.sha256(first_payload).hexdigest(),
                    size_bytes=len(first_payload),
                    frame_count=2,
                ),
                ManifestSegment(
                    index=1,
                    sha256=hashlib.sha256(second.path.read_bytes()).hexdigest(),
                    size_bytes=second.byte_count,
                    frame_count=2,
                ),
            ),
        )

    def test_ingested_valid_status_confirms_without_reuploading(self) -> None:
        sealed = self._seal(0)
        self._commit(sealed)
        remote = _IngestionService()
        remote.status = SessionStatusResponse(
            session_id=self.session_id,
            validity_status=ValidityStatus.VALID,
            ingest_status=IngestStatus.INGESTED,
        )

        outcome = self._queue(remote).upload_next(_Tokens())

        self.assertIs(outcome, UploadCycleOutcome.CONFIRMED)
        self.assertEqual(remote.put_calls, [])
        self.assertEqual(remote.subject_keys, [])
        self.assertEqual(
            self.store.sync_handoff_state(str(self.session_id)), "CLOUD_CONFIRMED"
        )
        self.assertTrue(sealed.path.exists())

    def test_wrong_status_session_identity_never_confirms_another_handoff(self) -> None:
        sealed = self._seal(0)
        self._commit(sealed)
        remote = _IngestionService()
        remote.status = SessionStatusResponse(
            session_id=uuid4(),
            validity_status=ValidityStatus.VALID,
            ingest_status=IngestStatus.INGESTED,
        )

        outcome = self._queue(remote).upload_next(_Tokens())

        self.assertIs(outcome, UploadCycleOutcome.CONFLICT)
        self.assertEqual(self.store.sync_handoff_state(str(self.session_id)), "CONFLICT")

    def test_wrong_segment_list_session_identity_never_progresses_handoff(self) -> None:
        sealed = self._seal(0)
        self._commit(sealed)
        remote = _IngestionService()
        remote.list_response = SegmentListResponse(
            session_id=uuid4(),
            received=(),
            missing=(0,),
        )

        outcome = self._queue(remote).upload_next(_Tokens())

        self.assertIs(outcome, UploadCycleOutcome.CONFLICT)
        self.assertEqual(remote.put_calls, [])

    def test_segment_list_requires_acknowledged_receipt_status(self) -> None:
        sealed = self._seal(0)
        self._commit(sealed)
        payload = sealed.path.read_bytes()
        remote = _IngestionService()
        remote.received[0] = (
            SegmentMetadata(
                segment_index=0,
                start_frame_index=0,
                frame_count=2,
                start_monotonic_ns=0,
                end_monotonic_ns=5_000_000_000,
                compression="none",
                cipher="aes-256-gcm",
                size_bytes=len(payload),
                sha256=hashlib.sha256(payload).hexdigest(),
                payload_schema_version="raw-segment/1",
            ),
            payload,
        )
        remote.list_response = SegmentListResponse(
            session_id=self.session_id,
            received=(
                {
                    "index": 0,
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "status": SegmentReceiptStatus.CONFLICT,
                },
            ),
            missing=(),
        )

        outcome = self._queue(remote).upload_next(_Tokens())

        self.assertIs(outcome, UploadCycleOutcome.CONFLICT)
        self.assertEqual(remote.put_calls, [])

    def test_segment_acknowledgement_binds_session_index_and_receipt_status(self) -> None:
        sealed = self._seal(0)
        self._commit(sealed)
        remote = _IngestionService()
        remote.acknowledgement = SegmentAcknowledgement(
            session_id=uuid4(),
            index=1,
            sha256=hashlib.sha256(sealed.path.read_bytes()).hexdigest(),
            status=SegmentReceiptStatus.CONFLICT,
            object_key="objects/wrong-handoff",
        )

        outcome = self._queue(remote).upload_next(_Tokens())

        self.assertIs(outcome, UploadCycleOutcome.CONFLICT)
        self.assertNotEqual(
            self.store.sync_handoff_state(str(self.session_id)), "CLOUD_CONFIRMED"
        )

    def test_completion_response_binds_session_manifest_and_ingest_status(self) -> None:
        sealed = self._seal(0)
        self._commit(sealed)
        remote = _IngestionService()
        remote.completion_response = ManifestCompletionResponse(
            session_id=uuid4(),
            ingest_status=IngestStatus.RECEIVING,
            manifest_sha256="0" * 64,
        )

        outcome = self._queue(remote).upload_next(_Tokens())

        self.assertIs(outcome, UploadCycleOutcome.CONFLICT)
        self.assertNotEqual(
            self.store.sync_handoff_state(str(self.session_id)), "CLOUD_CONFIRMED"
        )

    def test_lost_complete_response_reconciles_after_restart_without_duplicates(
        self,
    ) -> None:
        sealed = self._seal(0)
        self._commit(sealed)
        remote = _IngestionService()
        remote.lose_complete_response_once = True
        clock = _Clock()

        self.assertIs(
            self._queue(remote, clock=clock).upload_next(_Tokens()),
            UploadCycleOutcome.DEFERRED,
        )
        self.assertEqual(self.store.sync_handoff_state(str(self.session_id)), "RETRY_WAIT")
        self.assertTrue(sealed.path.exists())
        self.store.close()
        self.store = StateStore(
            self.root / "state.sqlite3", SensitiveBlobCodec(self.keys)
        )
        self.store.recover_interrupted_state(recovered_at_ns=2_000_000_000)
        clock.value = 2_000_000_000

        _, retry_at_ns, _ = self.store.sync_handoff_retry_state(str(self.session_id))
        assert retry_at_ns is not None
        self.assertGreater(retry_at_ns, clock.value)
        self.assertIs(
            self._queue(remote, clock=clock).upload_next(_Tokens()),
            UploadCycleOutcome.IDLE,
        )
        self.assertEqual(self.store.sync_handoff_state(str(self.session_id)), "RETRY_WAIT")

        clock.value = retry_at_ns
        outcome = self._queue(remote, clock=clock).upload_next(_Tokens())

        self.assertIs(outcome, UploadCycleOutcome.CONFIRMED)
        self.assertEqual(remote.put_calls, [0])
        self.assertEqual(len(remote.subject_keys), 1)
        self.assertEqual(len(remote.consent_keys), 1)
        self.assertEqual(len(remote.session_keys), 1)
        self.assertEqual(len(remote.complete_keys), 1)
        self.assertTrue(sealed.path.exists())

    def test_restart_preserves_equal_jitter_and_retry_after_deadlines(self) -> None:
        """A restart must not lease durable backoff work before its due time."""

        sealed = self._seal(0)
        self._commit(sealed)
        remote = _IngestionService()
        remote.failures["status"] = [
            UploadRetryable("temporary"),
            UploadRetryable("rate limited", retry_after_seconds=60.0),
        ]
        clock = _Clock()

        self.assertIs(
            self._queue(remote, clock=clock, random_fraction=lambda: 0.0).upload_next(
                _Tokens()
            ),
            UploadCycleOutcome.DEFERRED,
        )
        self.assertEqual(
            self.store.sync_handoff_retry_state(str(self.session_id)),
            (1, 3_500_000_000, "E-SYN-001"),
        )

        self.store.close()
        self.store = StateStore(
            self.root / "state.sqlite3", SensitiveBlobCodec(self.keys)
        )
        self.store.recover_interrupted_state(recovered_at_ns=2_000_000_000)
        clock.value = 2_000_000_000
        self.assertIs(
            self._queue(remote, clock=clock).upload_next(_Tokens()),
            UploadCycleOutcome.IDLE,
        )
        self.assertEqual(self.store.sync_handoff_state(str(self.session_id)), "RETRY_WAIT")

        clock.value = 3_500_000_000
        self.assertIs(
            self._queue(remote, clock=clock).upload_next(_Tokens()),
            UploadCycleOutcome.DEFERRED,
        )
        self.assertEqual(
            self.store.sync_handoff_retry_state(str(self.session_id)),
            (2, 63_500_000_000, "E-SYN-001"),
        )

        self.store.close()
        self.store = StateStore(
            self.root / "state.sqlite3", SensitiveBlobCodec(self.keys)
        )
        self.store.recover_interrupted_state(recovered_at_ns=4_000_000_000)
        clock.value = 4_000_000_000
        self.assertIs(
            self._queue(remote, clock=clock).upload_next(_Tokens()),
            UploadCycleOutcome.IDLE,
        )
        self.assertEqual(self.store.sync_handoff_state(str(self.session_id)), "RETRY_WAIT")

    def test_retry_delay_uses_durable_attempt_count_and_equal_jitter_bounds(
        self,
    ) -> None:
        sealed = self._seal(0)
        self._commit(sealed)
        remote = _IngestionService()
        remote.failures["status"] = [
            UploadRetryable("temporary"),
            UploadRetryable("temporary"),
        ]
        fractions = iter((0.0, 1.0))
        clock = _Clock()
        queue = self._queue(
            remote,
            clock=clock,
            random_fraction=lambda: next(fractions),
        )

        self.assertIs(queue.upload_next(_Tokens()), UploadCycleOutcome.DEFERRED)
        attempt, due_ns, error_code = self.store.sync_handoff_retry_state(
            str(self.session_id)
        )
        self.assertEqual((attempt, due_ns, error_code), (1, 3_500_000_000, "E-SYN-001"))

        assert due_ns is not None
        clock.value = due_ns
        self.assertIs(queue.upload_next(_Tokens()), UploadCycleOutcome.DEFERRED)
        attempt, due_ns, error_code = self.store.sync_handoff_retry_state(
            str(self.session_id)
        )
        self.assertEqual(
            (attempt, due_ns, error_code),
            (2, 13_500_000_000, "E-SYN-001"),
        )

    def test_retry_delay_caps_and_larger_retry_after_wins(self) -> None:
        sealed = self._seal(0)
        self._commit(sealed)
        remote = _IngestionService()
        remote.failures["status"] = [UploadRetryable("temporary")] * 12
        clock = _Clock()
        queue = self._queue(remote, clock=clock, random_fraction=lambda: 1.0)

        for _ in range(12):
            before = clock.value
            self.assertIs(queue.upload_next(_Tokens()), UploadCycleOutcome.DEFERRED)
            _attempt, due_ns, _error_code = self.store.sync_handoff_retry_state(
                str(self.session_id)
            )
            assert due_ns is not None
            self.assertLessEqual(due_ns - before, 900_000_000_000)
            clock.value = due_ns
        self.assertEqual(due_ns - before, 900_000_000_000)

        remote.failures["status"] = [
            UploadRetryable("rate limited", retry_after_seconds=1_200.0)
        ]
        before = clock.value
        self.assertIs(queue.upload_next(_Tokens()), UploadCycleOutcome.DEFERRED)
        _attempt, due_ns, _error_code = self.store.sync_handoff_retry_state(
            str(self.session_id)
        )
        self.assertEqual(due_ns, before + 1_200_000_000_000)

    def test_authentication_refreshes_once_and_restarts_with_the_new_token(self) -> None:
        sealed = self._seal(0)
        self._commit(sealed)
        remote = _IngestionService()
        remote.failures["status"] = [UploadAuthenticationRequired("expired")]
        tokens = _Tokens()

        outcome = self._queue(remote).upload_next(tokens)

        self.assertIs(outcome, UploadCycleOutcome.CONFIRMED)
        self.assertEqual(tokens.refresh_calls, 1)
        self.assertGreaterEqual(tokens.current_calls, 2)
        self.assertEqual(
            remote.calls[:3],
            ["status:first-access-token", "status:refreshed-access-token", "subject"],
        )

    def test_temporarily_unavailable_envelope_key_defers_instead_of_conflicting(self) -> None:
        sealed = self._seal(0)
        self._commit(sealed)
        original = self.keys.get_key
        self.keys.get_key = lambda: (_ for _ in ()).throw(  # type: ignore[method-assign]
            OSError("keychain is temporarily unavailable")
        )
        try:
            outcome = self._queue(_IngestionService()).upload_next(_Tokens())
        finally:
            self.keys.get_key = original  # type: ignore[method-assign]

        self.assertIs(outcome, UploadCycleOutcome.DEFERRED)
        self.assertEqual(self.store.sync_handoff_state(str(self.session_id)), "RETRY_WAIT")

    def test_temporarily_unavailable_segment_key_defers_instead_of_conflicting(self) -> None:
        sealed = self._seal(0)
        self._commit(sealed)
        original = self.keys.get_key
        calls = 0

        def unavailable_on_segment_decrypt() -> bytes:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("keychain is temporarily unavailable")
            return original()

        self.keys.get_key = unavailable_on_segment_decrypt  # type: ignore[method-assign]
        try:
            outcome = self._queue(_IngestionService()).upload_next(_Tokens())
        finally:
            self.keys.get_key = original  # type: ignore[method-assign]

        self.assertIs(outcome, UploadCycleOutcome.DEFERRED)
        self.assertEqual(self.store.sync_handoff_state(str(self.session_id)), "RETRY_WAIT")

    def test_corrupt_encrypted_envelope_remains_a_conflict(self) -> None:
        sealed = self._seal(0)
        self._commit(sealed)
        with self.store._connection:
            self.store._connection.execute(
                "UPDATE sync_handoffs SET upload_envelope=? WHERE session_id=?",
                (b"not-an-encrypted-envelope", str(self.session_id)),
            )

        outcome = self._queue(_IngestionService()).upload_next(_Tokens())

        self.assertIs(outcome, UploadCycleOutcome.CONFLICT)
        self.assertEqual(self.store.sync_handoff_state(str(self.session_id)), "CONFLICT")

    def test_local_length_failure_conflicts_without_deleting_data(self) -> None:
        sealed = self._seal(0)
        self._commit(sealed)
        sealed.path.write_bytes(sealed.path.read_bytes() + b"x")

        outcome = self._queue(_IngestionService()).upload_next(_Tokens())

        self.assertIs(outcome, UploadCycleOutcome.CONFLICT)
        self.assertEqual(self.store.sync_handoff_state(str(self.session_id)), "CONFLICT")
        self.assertTrue(sealed.path.exists())

    def test_local_digest_failure_conflicts_without_deleting_data(self) -> None:
        sealed = self._seal(0)
        self._commit(sealed)
        payload = bytearray(sealed.path.read_bytes())
        payload[-9] ^= 1
        sealed.path.write_bytes(payload)

        outcome = self._queue(_IngestionService()).upload_next(_Tokens())

        self.assertIs(outcome, UploadCycleOutcome.CONFLICT)
        self.assertEqual(self.store.sync_handoff_state(str(self.session_id)), "CONFLICT")
        self.assertTrue(sealed.path.exists())

    def test_local_path_failure_conflicts_without_reading_outside_repository(self) -> None:
        sealed = self._seal(0)
        self._commit(sealed)
        with self.store._connection:
            self.store._connection.execute(
                "UPDATE segments SET relative_path='../outside.ffps' WHERE session_id=?",
                (str(self.session_id),),
            )

        outcome = self._queue(_IngestionService()).upload_next(_Tokens())

        self.assertIs(outcome, UploadCycleOutcome.CONFLICT)
        self.assertEqual(self.store.sync_handoff_state(str(self.session_id)), "CONFLICT")
        self.assertTrue(sealed.path.exists())


class HttpIngestionClientTests(unittest.TestCase):
    def test_http_client_ignores_environment_proxy_and_certificate_overrides(self) -> None:
        terminal_id = uuid4()
        with patch("client.sync.persistent_upload.httpx.Client") as constructor:
            HttpIngestionClient("https://cloud.test", terminal_id=terminal_id)

        self.assertIs(constructor.call_args.kwargs["trust_env"], False)

    def test_request_carries_the_bound_terminal_identity(self) -> None:
        terminal_id = uuid4()
        session_id = uuid4()
        observed_headers: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            observed_headers.update(request.headers)
            return httpx.Response(
                201,
                json={
                    "data": {
                        "session_id": str(session_id),
                        "ingest_status": "RECEIVING",
                        "idempotent_replay": False,
                    }
                },
            )

        client = HttpIngestionClient(
            "https://cloud.test",
            terminal_id=terminal_id,
            transport=httpx.MockTransport(handler),
        )
        try:
            response = client.create_session(
                "access-token",
                SessionCreateRequest(
                    session_id=session_id,
                    subject_uuid=uuid4(),
                    consent_record_id=uuid4(),
                    site_id=None,
                    terminal_id=terminal_id,
                    client_installation_id=terminal_id,
                    device_id=uuid4(),
                    test_protocol=CloudTestProtocol(
                        id="standard-screening", version="1.0"
                    ),
                    versions={
                        "app": "0.1.0",
                        "protocol_profile": "do-p4864/1",
                        "payload_schema": "raw-segment/1",
                        "calibration": "calibration/1",
                    },
                    started_at=datetime.now(UTC),
                ),
                "session:stable",
            )
        finally:
            client.close()

        self.assertEqual(response.session_id, session_id)
        self.assertEqual(observed_headers["x-terminal-id"], str(terminal_id))
        self.assertEqual(observed_headers["authorization"], "Bearer access-token")

    def test_status_404_maps_to_none(self) -> None:
        client = HttpIngestionClient(
            "https://cloud.test",
            terminal_id=uuid4(),
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(
                    404,
                    json={
                        "error": {
                            "code": "E-API-404",
                            "message": "not found",
                            "retryable": False,
                            "action": "NONE",
                            "details": {},
                        }
                    },
                )
            ),
        )
        try:
            self.assertIsNone(client.get_status("access-token", uuid4()))
        finally:
            client.close()

    def test_http_errors_are_typed_and_preserve_safe_cloud_codes(self) -> None:
        cases = (
            (401, UploadAuthenticationRequired, "E-AUT-401"),
            (409, UploadConflict, "E-SYN-409"),
            (422, UploadBlocked, "E-CLD-422"),
            (503, UploadRetryable, "E-SYN-503"),
        )
        for status_code, expected_type, error_code in cases:
            with self.subTest(status_code=status_code):
                client = HttpIngestionClient(
                    "https://cloud.test",
                    terminal_id=uuid4(),
                    transport=httpx.MockTransport(
                        lambda _request,
                        status_code=status_code,
                        error_code=error_code: httpx.Response(
                            status_code,
                            json={
                                "error": {
                                    "code": error_code,
                                    "message": "safe error",
                                    "retryable": status_code >= 500,
                                    "action": "RETRY" if status_code >= 500 else "SUPPORT",
                                    "details": {},
                                },
                                "meta": {"request_id": str(uuid4())},
                            },
                        )
                    ),
                )
                try:
                    with self.assertRaises(expected_type) as raised:
                        client.get_status("secret-token-not-for-errors", uuid4())
                finally:
                    client.close()
                self.assertEqual(raised.exception.error_code, error_code)
                self.assertNotIn("secret-token-not-for-errors", str(raised.exception))

    def test_retry_after_is_parsed_for_rate_limit(self) -> None:
        client = HttpIngestionClient(
            "https://cloud.test",
            terminal_id=uuid4(),
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(
                    429,
                    headers={"Retry-After": "1200"},
                    json={
                        "error": {
                            "code": "E-SYN-429",
                            "message": "rate limited",
                            "retryable": True,
                            "action": "RETRY",
                            "details": {},
                        }
                    },
                )
            ),
        )
        try:
            with self.assertRaises(UploadRetryable) as raised:
                client.get_status("access-token", uuid4())
        finally:
            client.close()

        self.assertEqual(raised.exception.retry_after_seconds, 1_200.0)


if __name__ == "__main__":
    unittest.main()
