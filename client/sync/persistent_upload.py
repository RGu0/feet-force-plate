"""Durable client upload queue for immutable valid-session handoffs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import hashlib
from pathlib import Path
import time
from typing import Any, Protocol
from uuid import UUID

import httpx
from pydantic import ValidationError

from client.spool.segments import read_segment
from client.spool.state_store import KeyProvider, StateStore, SyncHandoff
from shared.contracts.client_sync import canonical_sha256, encode_segment_metadata
from shared.contracts.cloud import (
    IngestStatus,
    ManifestCompletionResponse,
    ManifestSegment,
    SegmentAcknowledgement,
    SegmentListResponse,
    SegmentMetadata,
    SessionCreateRequest,
    SessionCreateResponse,
    SessionManifest,
    SessionVersions,
    TestProtocol,
    ValidityStatus,
)


class UploadUnavailable(RuntimeError):
    """A safe retryable transport or temporary service failure."""


class UploadConflict(RuntimeError):
    """A non-retryable immutable server/local digest disagreement."""


class IngestionClient(Protocol):
    def create_session(
        self, access_token: str, request: SessionCreateRequest, idempotency_key: str
    ) -> SessionCreateResponse: ...

    def list_segments(self, access_token: str, session_id: UUID) -> SegmentListResponse: ...

    def put_segment(
        self,
        access_token: str,
        session_id: UUID,
        metadata: SegmentMetadata,
        payload: bytes,
    ) -> SegmentAcknowledgement: ...

    def complete_session(
        self,
        access_token: str,
        session_id: UUID,
        manifest: SessionManifest,
        idempotency_key: str,
    ) -> ManifestCompletionResponse: ...


@dataclass(frozen=True, slots=True)
class SessionUploadContext:
    """Authenticated installation context used to build each server session request."""

    site_id: UUID | None
    terminal_id: UUID
    device_id: UUID
    test_protocol: TestProtocol
    app_version: str
    protocol_profile: str
    payload_schema: str
    calibration: str
    config_snapshot: dict[str, Any] = field(default_factory=dict)

    def request_for(self, handoff: SyncHandoff) -> SessionCreateRequest:
        if handoff.consent_id is None:
            raise UploadConflict("valid upload handoff has no consent reference")
        try:
            session_id = UUID(handoff.session_id)
            subject_uuid = UUID(handoff.subject_uuid)
            consent_id = UUID(handoff.consent_id)
        except ValueError as exc:
            raise UploadConflict("upload handoff identifiers are not UUIDs") from exc
        return SessionCreateRequest(
            session_id=session_id,
            subject_uuid=subject_uuid,
            consent_record_id=consent_id,
            site_id=self.site_id,
            terminal_id=self.terminal_id,
            device_id=self.device_id,
            test_protocol=self.test_protocol,
            versions=SessionVersions(
                app=self.app_version,
                protocol_profile=self.protocol_profile,
                payload_schema=self.payload_schema,
                calibration=self.calibration,
            ),
            started_at=datetime.fromtimestamp(handoff.started_at_ns / 1_000_000_000, UTC),
            config_snapshot=self.config_snapshot,
        )


class PersistentUploadQueue:
    """Uploads one SQLite-leased handoff without ever deleting local raw bytes."""

    def __init__(
        self,
        store: StateStore,
        repository_root: str | Path,
        key_provider: KeyProvider,
        client: IngestionClient,
        context: SessionUploadContext,
        *,
        now_ns=time.time_ns,
        retry_delay_ns: int = 30_000_000_000,
    ) -> None:
        if retry_delay_ns <= 0:
            raise ValueError("retry_delay_ns must be positive")
        self._store = store
        self._root = Path(repository_root).resolve()
        self._keys = key_provider
        self._client = client
        self._context = context
        self._now_ns = now_ns
        self._retry_delay_ns = retry_delay_ns

    def upload_next(self, access_token: str) -> bool:
        handoff = self._store.lease_sync_handoff(now_ns=self._now_ns())
        if handoff is None:
            return False
        try:
            request = self._context.request_for(handoff)
            self._client.create_session(
                access_token,
                request,
                f"session:{handoff.session_id}:{handoff.manifest_sha256[:16]}",
            )
            local = self._local_segments(handoff)
            remote = self._client.list_segments(access_token, request.session_id)
            remote_by_index = {item.index: item.sha256 for item in remote.received}
            if set(remote_by_index) - set(local):
                raise UploadConflict("server has a segment outside the local manifest")
            for index, segment in local.items():
                accepted = remote_by_index.get(index)
                if accepted is not None:
                    if accepted != segment.metadata.sha256:
                        raise UploadConflict("server segment digest differs from local immutable file")
                    continue
                acknowledgement = self._client.put_segment(
                    access_token, request.session_id, segment.metadata, segment.payload
                )
                if acknowledgement.sha256 != segment.metadata.sha256:
                    raise UploadConflict("server acknowledgement digest differs from local immutable file")
            manifest = SessionManifest(
                segment_count=len(local),
                total_frames=sum(item.metadata.frame_count for item in local.values()),
                total_bytes=sum(item.metadata.size_bytes for item in local.values()),
                segments=tuple(
                    ManifestSegment(
                        index=index,
                        sha256=item.metadata.sha256,
                        size_bytes=item.metadata.size_bytes,
                        frame_count=item.metadata.frame_count,
                    )
                    for index, item in sorted(local.items())
                ),
                ended_at=datetime.fromtimestamp(handoff.ended_at_ns / 1_000_000_000, UTC),
                local_quality_outcome=ValidityStatus.VALID,
            )
            result = self._client.complete_session(
                access_token,
                request.session_id,
                manifest,
                f"complete:{handoff.session_id}:{canonical_sha256(manifest)[:16]}",
            )
            if result.ingest_status is not IngestStatus.INGESTED:
                raise UploadUnavailable("server did not confirm final manifest ingestion")
        except UploadConflict:
            self._store.mark_sync_handoff_conflict(handoff.session_id)
            return False
        except Exception:
            self._store.defer_sync_handoff(
                handoff.session_id,
                next_attempt_at_ns=self._now_ns() + self._retry_delay_ns,
            )
            return False
        now_ns = self._now_ns()
        self._store.mark_cloud_confirmed(handoff.session_id, confirmed_at_ns=now_ns)
        self._store.record_successful_online(now_ns)
        return True

    def _local_segments(self, handoff: SyncHandoff) -> dict[int, _LocalSegment]:
        local: dict[int, _LocalSegment] = {}
        for record in self._store.sync_handoff_segments(handoff.session_id):
            path = (self._root / record.relative_path).resolve()
            if self._root not in path.parents:
                raise UploadConflict("sealed segment path escapes the local repository")
            payload = path.read_bytes()
            if len(payload) != record.byte_count:
                raise UploadConflict("sealed segment length differs from SQLite record")
            restored = read_segment(path, self._keys)
            if restored.session_id != handoff.session_id or restored.segment_index in local:
                raise UploadConflict("sealed segments do not form one unambiguous session")
            metadata = SegmentMetadata(
                segment_index=restored.segment_index,
                start_frame_index=restored.frames[0].source_index,
                frame_count=len(restored.frames),
                start_monotonic_ns=restored.frames[0].host_monotonic_ns,
                end_monotonic_ns=restored.frames[-1].host_monotonic_ns,
                compression="none",
                cipher="aes-256-gcm",
                size_bytes=len(payload),
                sha256=hashlib.sha256(payload).hexdigest(),
                payload_schema_version=self._context.payload_schema,
            )
            local[metadata.segment_index] = _LocalSegment(metadata, payload)
        if sorted(local) != list(range(len(local))):
            raise UploadConflict("local segments are not contiguous from index zero")
        return local


@dataclass(frozen=True, slots=True)
class _LocalSegment:
    metadata: SegmentMetadata
    payload: bytes


class HttpIngestionClient:
    """Synchronous production adapter for the cloud ingestion HTTP contract."""

    def __init__(
        self,
        base_url: str,
        *,
        terminal_id: UUID,
        verify: bool | str = True,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client = httpx.Client(base_url=base_url.rstrip("/"), verify=verify, transport=transport)
        self._terminal_id = terminal_id

    def close(self) -> None:
        self._client.close()

    def create_session(
        self, access_token: str, request: SessionCreateRequest, idempotency_key: str
    ) -> SessionCreateResponse:
        return self._model_request(
            "POST", "/v1/sessions", SessionCreateResponse, access_token,
            headers={"Idempotency-Key": idempotency_key},
            json=request.model_dump(mode="json"),
        )

    def list_segments(self, access_token: str, session_id: UUID) -> SegmentListResponse:
        return self._model_request(
            "GET", f"/v1/sessions/{session_id}/segments", SegmentListResponse, access_token
        )

    def put_segment(
        self, access_token: str, session_id: UUID, metadata: SegmentMetadata, payload: bytes
    ) -> SegmentAcknowledgement:
        return self._model_request(
            "PUT", f"/v1/sessions/{session_id}/segments/{metadata.segment_index}",
            SegmentAcknowledgement, access_token,
            headers={
                "X-Content-SHA256": metadata.sha256,
                "X-Schema-Version": metadata.payload_schema_version,
                "X-Segment-Metadata": encode_segment_metadata(metadata),
                "Content-Type": "application/vnd.feetforceplate.segment.v1+octet-stream",
            },
            content=payload,
        )

    def complete_session(
        self, access_token: str, session_id: UUID, manifest: SessionManifest, idempotency_key: str
    ) -> ManifestCompletionResponse:
        return self._model_request(
            "POST", f"/v1/sessions/{session_id}/complete", ManifestCompletionResponse, access_token,
            headers={
                "Idempotency-Key": idempotency_key,
                "X-Content-SHA256": canonical_sha256(manifest),
                "X-Schema-Version": manifest.schema_version,
            },
            json=manifest.model_dump(mode="json"),
        )

    def _model_request(
        self,
        method: str,
        path: str,
        model,
        access_token: str,
        *,
        headers: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
        content: bytes | None = None,
    ):
        request_headers = {
            "Authorization": f"Bearer {access_token}",
            "X-Terminal-ID": str(self._terminal_id),
        }
        request_headers.update(headers or {})
        try:
            response = self._client.request(method, path, headers=request_headers, json=json, content=content)
        except httpx.HTTPError as exc:
            raise UploadUnavailable("upload service is unavailable") from exc
        if response.status_code == 409:
            raise UploadConflict("server rejected immutable upload as conflicting")
        if response.status_code == 429 or response.status_code >= 500:
            raise UploadUnavailable("upload service is temporarily unavailable")
        if response.status_code >= 400:
            raise UploadConflict("server rejected upload request")
        try:
            return model.model_validate(response.json()["data"])
        except (KeyError, TypeError, ValueError, ValidationError) as exc:
            raise UploadUnavailable("upload service returned an invalid response") from exc


__all__ = [
    "HttpIngestionClient",
    "PersistentUploadQueue",
    "SessionUploadContext",
    "UploadConflict",
    "UploadUnavailable",
]
