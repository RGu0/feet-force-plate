"""Durable client upload queue for immutable valid-session handoffs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from enum import StrEnum
import hashlib
from pathlib import Path
import random
import re
import time
from typing import Any, Protocol
from uuid import UUID

import httpx
from pydantic import ValidationError
from techflex_cloud_foundation import SecureTransport

from client.spool.segments import SegmentIntegrityError, read_segment
from client.spool.state_store import (
    KeyProvider,
    KeyProviderUnavailable,
    StateStore,
    SyncHandoff,
)
from shared.contracts.client_sync import (
    FormalUploadEnvelope,
    canonical_sha256,
    encode_segment_metadata,
)
from shared.contracts.cloud import (
    ConsentCreateRequest,
    ConsentResponse,
    ErrorResponse,
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
    TestProtocol,
    ValidityStatus,
)


_SAFE_ERROR_CODE = re.compile(r"^E-[A-Z]{3}-[0-9]{3}$")
_RETRY_BASE_SECONDS = 5.0
_RETRY_CAP_SECONDS = 900.0


class UploadError(RuntimeError):
    """Safe upload failure carrying only a diagnostic code and generic message."""

    def __init__(self, message: str, *, error_code: str) -> None:
        super().__init__(message)
        self.error_code = error_code


class UploadRetryable(UploadError):
    """A transport or temporary service failure that keeps the handoff retryable."""

    def __init__(
        self,
        message: str,
        *,
        retry_after_seconds: float | None = None,
        error_code: str = "E-SYN-001",
    ) -> None:
        if retry_after_seconds is not None and retry_after_seconds < 0:
            raise ValueError("retry_after_seconds cannot be negative")
        super().__init__(message, error_code=error_code)
        self.retry_after_seconds = retry_after_seconds


class UploadAuthenticationRequired(UploadError):
    """The current access token must be refreshed before one safe retry."""

    def __init__(self, message: str, *, error_code: str = "E-AUT-001") -> None:
        super().__init__(message, error_code=error_code)


class UploadConflict(UploadError):
    """A non-retryable immutable server/local disagreement."""

    def __init__(self, message: str, *, error_code: str = "E-SYN-409") -> None:
        super().__init__(message, error_code=error_code)


class UploadBlocked(UploadError):
    """A non-retryable contract or authorization rejection."""

    def __init__(self, message: str, *, error_code: str = "E-SYN-400") -> None:
        super().__init__(message, error_code=error_code)


class UploadCycleOutcome(StrEnum):
    IDLE = "IDLE"
    CONFIRMED = "CONFIRMED"
    DEFERRED = "DEFERRED"
    CONFLICT = "CONFLICT"
    BLOCKED = "BLOCKED"


class UploadTokenProvider(Protocol):
    def current_access_token(self) -> str: ...

    def refresh(self) -> object: ...


class IngestionClient(Protocol):
    def get_status(
        self, access_token: str, session_id: UUID
    ) -> SessionStatusResponse | None: ...

    def create_subject(
        self,
        access_token: str,
        request: SubjectCreateRequest,
        idempotency_key: str,
    ) -> SubjectSummary: ...

    def create_consent(
        self,
        access_token: str,
        request: ConsentCreateRequest,
        idempotency_key: str,
    ) -> ConsentResponse: ...

    def create_session(
        self, access_token: str, request: SessionCreateRequest, idempotency_key: str
    ) -> SessionCreateResponse: ...

    def list_segments(
        self, access_token: str, session_id: UUID
    ) -> SegmentListResponse: ...

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
    """Legacy construction contract retained until packaged composition migrates."""

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
            client_installation_id=self.terminal_id,
            device_id=self.device_id,
            test_protocol=self.test_protocol,
            versions=SessionVersions(
                app=self.app_version,
                protocol_profile=self.protocol_profile,
                payload_schema=self.payload_schema,
                calibration=self.calibration,
            ),
            started_at=datetime.fromtimestamp(
                handoff.started_at_ns / 1_000_000_000, UTC
            ),
            config_snapshot=self.config_snapshot,
        )


def subject_key(envelope: FormalUploadEnvelope) -> str:
    return f"subject:{canonical_sha256(envelope.subject)}"


def consent_key(envelope: FormalUploadEnvelope) -> str:
    return f"consent:{canonical_sha256(envelope.consent)}"


def session_key(envelope: FormalUploadEnvelope) -> str:
    return f"session:{canonical_sha256(envelope.session_request())}"


def completion_key(manifest: SessionManifest) -> str:
    return f"complete:{canonical_sha256(manifest)}"


class PersistentUploadQueue:
    """Uploads one SQLite-leased handoff without ever deleting local raw bytes."""

    def __init__(
        self,
        store: StateStore,
        repository_root: str | Path,
        key_provider: KeyProvider,
        client: IngestionClient,
        *,
        now_ns=time.time_ns,
        random_fraction=random.random,
    ) -> None:
        self._store = store
        self._root = Path(repository_root).resolve()
        self._keys = key_provider
        self._client = client
        self._now_ns = now_ns
        self._random_fraction = random_fraction

    def upload_next(
        self, token_provider: UploadTokenProvider
    ) -> UploadCycleOutcome:
        handoff = self._store.lease_sync_handoff(now_ns=self._now_ns())
        if handoff is None:
            return UploadCycleOutcome.IDLE
        try:
            access_token = token_provider.current_access_token()
        except Exception:
            return self._defer(
                handoff,
                UploadRetryable(
                    "upload authentication is temporarily unavailable",
                    error_code="E-AUT-001",
                ),
            )
        try:
            return self._upload_handoff(handoff, access_token)
        except UploadAuthenticationRequired:
            try:
                token_provider.refresh()
                access_token = token_provider.current_access_token()
            except Exception:
                return self._defer(
                    handoff,
                    UploadRetryable(
                        "upload authentication refresh failed",
                        error_code="E-AUT-001",
                    ),
                )
            try:
                return self._upload_handoff(handoff, access_token)
            except UploadAuthenticationRequired:
                return self._defer(
                    handoff,
                    UploadRetryable(
                        "upload authentication remains unavailable",
                        error_code="E-AUT-001",
                    ),
                )
            except UploadError as exc:
                return self._transition_failure(handoff, exc)
            except Exception:
                return self._block_unexpected(handoff)
        except UploadError as exc:
            return self._transition_failure(handoff, exc)
        except Exception:
            return self._block_unexpected(handoff)

    def _upload_handoff(
        self, handoff: SyncHandoff, access_token: str
    ) -> UploadCycleOutcome:
        try:
            envelope = self._store.sync_handoff_envelope(handoff.session_id)
        except KeyProviderUnavailable as exc:
            raise UploadRetryable(
                "local upload key is temporarily unavailable",
                error_code="E-SYN-503",
            ) from exc
        except Exception as exc:
            raise UploadConflict("formal upload envelope is unavailable") from exc

        status = self._client.get_status(access_token, envelope.session_id)
        if status is not None:
            self._require_status_session(status, envelope.session_id)
            if status.ingest_status is IngestStatus.INGESTED:
                self._require_valid(status)
                return self._confirm(handoff)
            self._require_continuable(status)

        self._client.create_subject(
            access_token,
            envelope.subject,
            subject_key(envelope),
        )
        self._client.create_consent(
            access_token,
            envelope.consent,
            consent_key(envelope),
        )
        self._client.create_session(
            access_token,
            envelope.session_request(),
            session_key(envelope),
        )
        try:
            local = self._local_segments(handoff, envelope)
        except KeyProviderUnavailable as exc:
            raise UploadRetryable(
                "local upload key is temporarily unavailable",
                error_code="E-SYN-503",
            ) from exc
        remote = self._client.list_segments(access_token, envelope.session_id)
        self._require_segment_list(remote, envelope.session_id, local)
        remote_by_index = {item.index: item.sha256 for item in remote.received}
        if set(remote_by_index) - set(local):
            raise UploadConflict("server has a segment outside the local manifest")
        for index, segment in local.items():
            accepted = remote_by_index.get(index)
            if accepted is not None:
                if accepted != segment.metadata.sha256:
                    raise UploadConflict(
                        "server segment digest differs from local immutable file"
                    )
                continue
            acknowledgement = self._client.put_segment(
                access_token,
                envelope.session_id,
                segment.metadata,
                segment.payload,
            )
            self._require_acknowledgement(
                acknowledgement,
                session_id=envelope.session_id,
                segment=segment.metadata,
            )

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
            ended_at=datetime.fromtimestamp(
                handoff.ended_at_ns / 1_000_000_000, UTC
            ),
            local_quality_outcome=ValidityStatus.VALID,
        )
        completion = self._client.complete_session(
            access_token,
            envelope.session_id,
            manifest,
            completion_key(manifest),
        )
        self._require_completion(
            completion,
            session_id=envelope.session_id,
            manifest_sha256=canonical_sha256(manifest),
        )
        final_status = self._client.get_status(access_token, envelope.session_id)
        if final_status is None:
            raise UploadRetryable("server status is not yet available")
        self._require_status_session(final_status, envelope.session_id)
        if final_status.ingest_status is not IngestStatus.INGESTED:
            self._require_continuable(final_status)
            raise UploadRetryable(
                "server has not completed manifest ingestion",
                retry_after_seconds=final_status.retry_after_seconds,
            )
        self._require_valid(final_status)
        return self._confirm(handoff)

    def _confirm(self, handoff: SyncHandoff) -> UploadCycleOutcome:
        now_ns = self._now_ns()
        self._store.mark_cloud_confirmed(handoff.session_id, confirmed_at_ns=now_ns)
        self._store.record_successful_online(now_ns)
        return UploadCycleOutcome.CONFIRMED

    @staticmethod
    def _require_valid(status: SessionStatusResponse) -> None:
        if status.validity_status is not ValidityStatus.VALID:
            raise UploadConflict("ingested session is not valid")

    @staticmethod
    def _require_status_session(
        status: SessionStatusResponse, session_id: UUID
    ) -> None:
        if status.session_id != session_id:
            raise UploadConflict("server status belongs to another session")

    @staticmethod
    def _require_segment_list(
        response: SegmentListResponse,
        session_id: UUID,
        local: dict[int, _LocalSegment],
    ) -> None:
        if response.session_id != session_id:
            raise UploadConflict("server segment list belongs to another session")
        received_indices: set[int] = set()
        for receipt in response.received:
            if receipt.index in received_indices or receipt.index not in local:
                raise UploadConflict("server segment list has an invalid received index")
            if receipt.status is not SegmentReceiptStatus.ACKNOWLEDGED:
                raise UploadConflict("server segment list has a non-acknowledged receipt")
            received_indices.add(receipt.index)
        missing_indices = set(response.missing)
        if (
            len(missing_indices) != len(response.missing)
            or not missing_indices.issubset(local)
            or received_indices & missing_indices
        ):
            raise UploadConflict("server segment list has an invalid missing index")

    @staticmethod
    def _require_acknowledgement(
        acknowledgement: SegmentAcknowledgement,
        *,
        session_id: UUID,
        segment: SegmentMetadata,
    ) -> None:
        if acknowledgement.session_id != session_id:
            raise UploadConflict("server segment acknowledgement belongs to another session")
        if acknowledgement.index != segment.segment_index:
            raise UploadConflict("server acknowledged another segment index")
        if acknowledgement.status is not SegmentReceiptStatus.ACKNOWLEDGED:
            raise UploadConflict("server did not acknowledge the immutable segment")
        if acknowledgement.sha256 != segment.sha256:
            raise UploadConflict(
                "server acknowledgement digest differs from local immutable file"
            )

    @staticmethod
    def _require_completion(
        completion: ManifestCompletionResponse,
        *,
        session_id: UUID,
        manifest_sha256: str,
    ) -> None:
        if completion.session_id != session_id:
            raise UploadConflict("server completion belongs to another session")
        if completion.manifest_sha256 != manifest_sha256:
            raise UploadConflict("server completed a different immutable manifest")
        if completion.ingest_status is not IngestStatus.INGESTED:
            raise UploadConflict("server completion has an unexpected ingest status")

    @staticmethod
    def _require_continuable(status: SessionStatusResponse) -> None:
        if status.ingest_status in {IngestStatus.CONFLICT, IngestStatus.QUARANTINED}:
            raise UploadConflict("server session is not continuable")
        if status.validity_status in {
            ValidityStatus.INVALID,
            ValidityStatus.INCOMPLETE,
            ValidityStatus.FAILED,
        }:
            raise UploadConflict("server validity conflicts with local valid session")

    def _transition_failure(
        self, handoff: SyncHandoff, exc: UploadError
    ) -> UploadCycleOutcome:
        if isinstance(exc, UploadRetryable):
            return self._defer(handoff, exc)
        if isinstance(exc, UploadConflict):
            self._store.mark_sync_handoff_conflict(handoff.session_id)
            return UploadCycleOutcome.CONFLICT
        if isinstance(exc, UploadBlocked):
            self._store.mark_sync_handoff_blocked(
                handoff.session_id,
                error_code=exc.error_code,
            )
            return UploadCycleOutcome.BLOCKED
        return self._block_unexpected(handoff)

    def _defer(
        self, handoff: SyncHandoff, exc: UploadRetryable
    ) -> UploadCycleOutcome:
        delay_seconds = self._retry_delay_seconds(
            handoff.attempt_count,
            retry_after_seconds=exc.retry_after_seconds,
        )
        self._store.defer_sync_handoff(
            handoff.session_id,
            error_code=exc.error_code,
            next_attempt_at_ns=self._now_ns() + int(delay_seconds * 1_000_000_000),
        )
        return UploadCycleOutcome.DEFERRED

    def _retry_delay_seconds(
        self,
        attempt_count: int,
        *,
        retry_after_seconds: float | None,
    ) -> float:
        if attempt_count < 1:
            raise ValueError("attempt_count must be positive")
        fraction = float(self._random_fraction())
        if not 0.0 <= fraction <= 1.0:
            raise ValueError("random_fraction must return a value between zero and one")
        if attempt_count >= 9:
            exponential_cap = _RETRY_CAP_SECONDS
        else:
            exponential_cap = min(
                _RETRY_CAP_SECONDS,
                _RETRY_BASE_SECONDS * (2 ** (attempt_count - 1)),
            )
        equal_jitter = exponential_cap / 2 + fraction * exponential_cap / 2
        return max(equal_jitter, retry_after_seconds or 0.0)

    def _block_unexpected(self, handoff: SyncHandoff) -> UploadCycleOutcome:
        self._store.mark_sync_handoff_blocked(
            handoff.session_id,
            error_code="E-SYN-500",
        )
        return UploadCycleOutcome.BLOCKED

    def _local_segments(
        self,
        handoff: SyncHandoff,
        envelope: FormalUploadEnvelope,
    ) -> dict[int, _LocalSegment]:
        local: dict[int, _LocalSegment] = {}
        try:
            records = self._store.sync_handoff_segments(handoff.session_id)
        except KeyError as exc:
            raise UploadConflict("valid handoff has no local segments") from exc
        for record in records:
            path = (self._root / record.relative_path).resolve()
            if path != self._root and self._root not in path.parents:
                raise UploadConflict("sealed segment path escapes the local repository")
            try:
                payload = path.read_bytes()
            except OSError as exc:
                raise UploadConflict("sealed segment file is unavailable") from exc
            if len(payload) != record.byte_count:
                raise UploadConflict("sealed segment length differs from SQLite record")
            try:
                restored = read_segment(path, self._keys)
            except (OSError, SegmentIntegrityError) as exc:
                raise UploadConflict("sealed segment integrity verification failed") from exc
            if restored.session_id != handoff.session_id or restored.segment_index in local:
                raise UploadConflict(
                    "sealed segments do not form one unambiguous session"
                )
            if (
                restored.versions.get("payload_schema")
                != envelope.versions.payload_schema
            ):
                raise UploadConflict(
                    "sealed segment payload schema differs from upload envelope"
                )
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
                payload_schema_version=envelope.versions.payload_schema,
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
        self._client = SecureTransport(
            base_url,
            verify=verify,
            transport=transport,
        )
        self._terminal_id = terminal_id

    def close(self) -> None:
        self._client.close()

    def get_status(
        self, access_token: str, session_id: UUID
    ) -> SessionStatusResponse | None:
        return self._model_request(
            "GET",
            f"/v1/sessions/{session_id}/status",
            SessionStatusResponse,
            access_token,
            not_found_none=True,
        )

    def create_subject(
        self,
        access_token: str,
        request: SubjectCreateRequest,
        idempotency_key: str,
    ) -> SubjectSummary:
        return self._model_request(
            "POST",
            "/v1/subjects",
            SubjectSummary,
            access_token,
            headers={"Idempotency-Key": idempotency_key},
            json=request.model_dump(mode="json"),
        )

    def create_consent(
        self,
        access_token: str,
        request: ConsentCreateRequest,
        idempotency_key: str,
    ) -> ConsentResponse:
        return self._model_request(
            "POST",
            "/v1/consents",
            ConsentResponse,
            access_token,
            headers={"Idempotency-Key": idempotency_key},
            json=request.model_dump(mode="json"),
        )

    def create_session(
        self, access_token: str, request: SessionCreateRequest, idempotency_key: str
    ) -> SessionCreateResponse:
        payload = request.model_dump(mode="json")
        try:
            return self._model_request(
                "POST",
                "/v1/sessions",
                SessionCreateResponse,
                access_token,
                headers={"Idempotency-Key": idempotency_key},
                json=payload,
            )
        except UploadBlocked as exc:
            if exc.error_code != "E-API-422":
                raise
            legacy_payload = dict(payload)
            legacy_payload.pop("client_installation_id", None)
            return self._model_request(
                "POST",
                "/v1/sessions",
                SessionCreateResponse,
                access_token,
                headers={"Idempotency-Key": idempotency_key},
                json=legacy_payload,
            )

    def list_segments(
        self, access_token: str, session_id: UUID
    ) -> SegmentListResponse:
        return self._model_request(
            "GET",
            f"/v1/sessions/{session_id}/segments",
            SegmentListResponse,
            access_token,
        )

    def put_segment(
        self,
        access_token: str,
        session_id: UUID,
        metadata: SegmentMetadata,
        payload: bytes,
    ) -> SegmentAcknowledgement:
        return self._model_request(
            "PUT",
            f"/v1/sessions/{session_id}/segments/{metadata.segment_index}",
            SegmentAcknowledgement,
            access_token,
            headers={
                "X-Content-SHA256": metadata.sha256,
                "X-Schema-Version": metadata.payload_schema_version,
                "X-Segment-Metadata": encode_segment_metadata(metadata),
                "Content-Type": "application/vnd.feetforceplate.segment.v1+octet-stream",
            },
            content=payload,
        )

    def complete_session(
        self,
        access_token: str,
        session_id: UUID,
        manifest: SessionManifest,
        idempotency_key: str,
    ) -> ManifestCompletionResponse:
        return self._model_request(
            "POST",
            f"/v1/sessions/{session_id}/complete",
            ManifestCompletionResponse,
            access_token,
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
        not_found_none: bool = False,
    ):
        request_headers = {
            "Authorization": f"Bearer {access_token}",
            "X-Terminal-ID": str(self._terminal_id),
        }
        request_headers.update(headers or {})
        try:
            response = self._client.request(
                method,
                path,
                headers=request_headers,
                json=json,
                content=content,
            )
        except httpx.HTTPError as exc:
            raise UploadRetryable("upload service is unavailable") from exc
        if response.status_code == 404 and not_found_none:
            return None
        self._raise_for_response(response)
        try:
            return model.model_validate(response.json()["data"])
        except (KeyError, TypeError, ValueError, ValidationError) as exc:
            raise UploadRetryable(
                "upload service returned an invalid response",
                error_code="E-SYN-502",
            ) from exc

    def _raise_for_response(self, response: httpx.Response) -> None:
        if response.status_code < 400:
            return
        error_code = self._safe_error_code(response)
        if response.status_code == 401:
            raise UploadAuthenticationRequired(
                "upload authentication is required",
                error_code=error_code,
            )
        if response.status_code == 409:
            raise UploadConflict(
                "server rejected immutable upload as conflicting",
                error_code=error_code,
            )
        if response.status_code == 429 or response.status_code >= 500:
            raise UploadRetryable(
                "upload service is temporarily unavailable",
                retry_after_seconds=self._retry_after_seconds(response),
                error_code=error_code,
            )
        raise UploadBlocked(
            "server rejected upload contract",
            error_code=error_code,
        )

    @staticmethod
    def _safe_error_code(response: httpx.Response) -> str:
        try:
            payload = response.json()
            parsed = ErrorResponse.model_validate({"error": payload["error"]})
        except (KeyError, TypeError, ValueError, ValidationError):
            parsed = None
        if parsed is not None and _SAFE_ERROR_CODE.fullmatch(parsed.error.code):
            return parsed.error.code
        family = "AUT" if response.status_code in {401, 403} else "SYN"
        return f"E-{family}-{min(response.status_code, 999):03d}"

    @staticmethod
    def _retry_after_seconds(response: httpx.Response) -> float | None:
        raw = response.headers.get("Retry-After")
        if raw is None:
            return None
        try:
            seconds = float(raw)
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(raw)
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=UTC)
                seconds = (retry_at - datetime.now(UTC)).total_seconds()
            except (TypeError, ValueError, OverflowError):
                return None
        return max(0.0, seconds)


__all__ = [
    "HttpIngestionClient",
    "PersistentUploadQueue",
    "SessionUploadContext",
    "UploadAuthenticationRequired",
    "UploadBlocked",
    "UploadConflict",
    "UploadCycleOutcome",
    "UploadRetryable",
    "UploadTokenProvider",
    "completion_key",
    "consent_key",
    "session_key",
    "subject_key",
]
