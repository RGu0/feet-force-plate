from __future__ import annotations

from datetime import UTC, datetime
import hashlib
from pathlib import Path
import tempfile
import unittest
from uuid import UUID, uuid4

import httpx
import numpy as np

from client.device.protocol import RawFrame
from client.spool.segments import ImmutableSegmentWriter, SealedSegment
from client.spool.state_store import (
    SensitiveBlobCodec,
    StateStore,
    ValidSegmentRecord,
)
from client.sync.persistent_upload import (
    HttpIngestionClient,
    PersistentUploadQueue,
    SessionUploadContext,
    UploadUnavailable,
)
from shared.contracts.cloud import (
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
    TestProtocol,
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
        self.unavailable_once = False

    def create_session(
        self,
        _access_token: str,
        request: SessionCreateRequest,
        _idempotency_key: str,
    ) -> SessionCreateResponse:
        return SessionCreateResponse(session_id=request.session_id, ingest_status=IngestStatus.RECEIVING)

    def list_segments(self, _access_token: str, session_id: UUID) -> SegmentListResponse:
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
        if self.unavailable_once:
            self.unavailable_once = False
            raise UploadUnavailable("network unavailable")
        self.received[metadata.segment_index] = (metadata, payload)
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
        _idempotency_key: str,
    ) -> ManifestCompletionResponse:
        self.manifests.append(manifest)
        for segment in manifest.segments:
            metadata, payload = self.received[segment.index]
            if (metadata.sha256, metadata.size_bytes) != (
                segment.sha256,
                segment.size_bytes,
            ) or payload != self.received[segment.index][1]:
                raise AssertionError("manifest does not describe received immutable bytes")
        return ManifestCompletionResponse(
            session_id=session_id,
            ingest_status=IngestStatus.INGESTED,
            manifest_sha256="a" * 64,
        )


class PersistentUploadQueueTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.keys = _Key()
        self.store = StateStore(self.root / "state.sqlite3", SensitiveBlobCodec(self.keys))
        self.session_id = uuid4()
        self.subject_id = uuid4()
        self.consent_id = uuid4()
        self.context = SessionUploadContext(
            site_id=None,
            terminal_id=uuid4(),
            device_id=uuid4(),
            test_protocol=TestProtocol(id="standard-screening", version="1.0"),
            app_version="0.1.0",
            protocol_profile="do-p4864/1",
            payload_schema="raw-segment/1",
            calibration="calibration/1",
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
            versions_json=b'{}',
            started_at_ns=0,
            ended_at_ns=20_000_000_000,
            manifest_sha256="b" * 64,
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

    def test_restart_resumes_only_missing_segments_and_retains_acknowledged_files(self) -> None:
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

        queue = PersistentUploadQueue(self.store, self.root, self.keys, remote, self.context)

        self.assertTrue(queue.upload_next("access-token"))
        self.assertEqual(set(remote.received), {0, 1})
        self.assertEqual(remote.received[1][1], second.path.read_bytes())
        self.assertEqual(self.store.sync_handoff_state(str(self.session_id)), "CLOUD_CONFIRMED")
        self.assertTrue(first.path.exists())
        self.assertTrue(second.path.exists())
        self.assertEqual(len(remote.manifests), 1)
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

    def test_network_failure_requeues_the_durable_handoff_after_process_restart(self) -> None:
        sealed = self._seal(0)
        self._commit(sealed)
        remote = _IngestionService()
        remote.unavailable_once = True
        queue = PersistentUploadQueue(self.store, self.root, self.keys, remote, self.context)

        self.assertFalse(queue.upload_next("access-token"))
        self.assertEqual(self.store.sync_handoff_state(str(self.session_id)), "RETRY_WAIT")
        self.assertTrue(sealed.path.exists())
        self.store.close()
        self.store = StateStore(self.root / "state.sqlite3", SensitiveBlobCodec(self.keys))
        self.store.recover_interrupted_state(recovered_at_ns=30_000_000_000)
        restarted = PersistentUploadQueue(self.store, self.root, self.keys, remote, self.context)

        self.assertTrue(restarted.upload_next("access-token"))
        self.assertEqual(self.store.sync_handoff_state(str(self.session_id)), "CLOUD_CONFIRMED")
        self.assertTrue(sealed.path.exists())


class HttpIngestionClientTests(unittest.TestCase):
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
                    test_protocol=TestProtocol(id="standard-screening", version="1.0"),
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


if __name__ == "__main__":
    unittest.main()
