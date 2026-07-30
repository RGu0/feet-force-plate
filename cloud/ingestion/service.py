from __future__ import annotations

from typing import AsyncIterable
from uuid import UUID

from cloud.api.auth import TerminalContext
from cloud.api.errors import (
    DigestMismatch,
    QualityGateRejected,
    SchemaUnsupported,
    SegmentDigestConflict,
)
from shared.contracts.client_sync import canonical_sha256
from shared.contracts.cloud import (
    ManifestCompletionResponse,
    ReceivedSegment,
    SegmentAcknowledgement,
    SegmentListResponse,
    SegmentMetadata,
    SegmentReceiptStatus,
    SessionCreateRequest,
    SessionCreateResponse,
    SessionManifest,
    SessionStatusResponse,
    ValidityStatus,
)

from .object_store import ObjectStore


class IngestionService:
    def __init__(
        self,
        repository,
        object_store: ObjectStore,
        *,
        supported_payload_schemas: set[str],
        supported_manifest_schemas: set[str],
    ) -> None:
        self._repository = repository
        self._objects = object_store
        self._payload_schemas = frozenset(supported_payload_schemas)
        self._manifest_schemas = frozenset(supported_manifest_schemas)

    async def create_session(
        self,
        context: TerminalContext,
        request: SessionCreateRequest,
        idempotency_key: str,
    ) -> SessionCreateResponse:
        context.ensure_active()
        if request.versions.payload_schema not in self._payload_schemas:
            raise SchemaUnsupported(
                "客户端原始分段模式不受支持",
                schema_version=request.versions.payload_schema,
            )
        return await self._repository.create_session(context, request, idempotency_key)

    async def put_segment(
        self,
        context: TerminalContext,
        session_id: UUID,
        route_index: int,
        metadata: SegmentMetadata,
        chunks: AsyncIterable[bytes],
    ) -> SegmentAcknowledgement:
        context.ensure_active()
        if route_index != metadata.segment_index:
            raise ValueError("route segment index must equal signed metadata index")
        if metadata.payload_schema_version not in self._payload_schemas:
            raise SchemaUnsupported(
                "分段模式不受支持", schema_version=metadata.payload_schema_version
            )
        session = await self._repository.session(context, session_id)
        if session.request.versions.payload_schema != metadata.payload_schema_version:
            raise SchemaUnsupported(
                "分段模式与会话模式不一致",
                session_schema=session.request.versions.payload_schema,
                segment_schema=metadata.payload_schema_version,
            )
        existing = await self._repository.get_segment(context, session_id, route_index)
        if existing is not None:
            if existing.metadata.sha256 != metadata.sha256:
                await self._repository.mark_segment_conflict(context, session_id, route_index)
                raise SegmentDigestConflict(
                    "同一分段索引已存在不同内容",
                    session_id=str(session_id),
                    segment_index=route_index,
                )
            return SegmentAcknowledgement(
                session_id=session_id,
                index=route_index,
                sha256=metadata.sha256,
                status=SegmentReceiptStatus.ACKNOWLEDGED,
                object_key=existing.object_key,
                idempotent_replay=True,
            )
        stored = await self._objects.put_segment(
            context.tenant_id, session_id, metadata, chunks
        )
        try:
            record = await self._repository.register_segment(
                context, session_id, metadata, stored.object_key
            )
        except SegmentDigestConflict:
            if not await self._repository.object_is_referenced(
                context.tenant_id, stored.object_key
            ):
                await self._objects.delete(stored.object_key)
            await self._repository.mark_segment_conflict(
                context, session_id, route_index
            )
            raise
        except Exception:
            if not await self._repository.object_is_referenced(
                context.tenant_id, stored.object_key
            ):
                await self._objects.delete(stored.object_key)
            raise
        return SegmentAcknowledgement(
            session_id=session_id,
            index=route_index,
            sha256=metadata.sha256,
            status=SegmentReceiptStatus.ACKNOWLEDGED,
            object_key=record.object_key,
        )

    async def list_segments(
        self, context: TerminalContext, session_id: UUID
    ) -> SegmentListResponse:
        accepted = await self._repository.list_segments(context, session_id)
        indices = [record.metadata.segment_index for record in accepted]
        expected_count = await self._repository.expected_segment_count(context, session_id)
        upper_bound = expected_count if expected_count is not None else max(indices, default=-1) + 1
        received_indices = set(indices)
        return SegmentListResponse(
            session_id=session_id,
            received=tuple(
                ReceivedSegment(
                    index=record.metadata.segment_index,
                    sha256=record.metadata.sha256,
                    status=SegmentReceiptStatus.ACKNOWLEDGED,
                )
                for record in accepted
            ),
            missing=tuple(index for index in range(upper_bound) if index not in received_indices),
        )

    async def complete_session(
        self,
        context: TerminalContext,
        session_id: UUID,
        manifest: SessionManifest,
        expected_sha256: str,
        idempotency_key: str,
    ) -> ManifestCompletionResponse:
        context.ensure_active()
        actual_sha256 = canonical_sha256(manifest)
        if actual_sha256 != expected_sha256:
            raise DigestMismatch(
                "最终清单请求摘要不一致",
                expected=expected_sha256,
                actual=actual_sha256,
            )
        if manifest.schema_version not in self._manifest_schemas:
            raise SchemaUnsupported(
                "最终清单模式不受支持", schema_version=manifest.schema_version
            )
        if manifest.local_quality_outcome is not ValidityStatus.VALID:
            raise QualityGateRejected(
                "未通过本地质量门控的会话不能启动正式分析",
                validity_status=manifest.local_quality_outcome.value,
            )
        await self._repository.session(context, session_id)
        stored = await self._objects.put_manifest(
            context.tenant_id, session_id, manifest, expected_sha256
        )
        try:
            return await self._repository.complete_manifest(
                context,
                session_id,
                manifest,
                expected_sha256,
                stored.object_key,
                idempotency_key,
            )
        except Exception:
            if not await self._repository.object_is_referenced(
                context.tenant_id, stored.object_key
            ):
                await self._objects.delete(stored.object_key)
            raise

    async def get_status(
        self, context: TerminalContext, session_id: UUID
    ) -> SessionStatusResponse:
        return await self._repository.status(context, session_id)
