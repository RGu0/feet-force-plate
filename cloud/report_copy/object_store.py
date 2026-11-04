"""Narrow private PDF adapter; callers never receive an object URL."""

from __future__ import annotations

from uuid import UUID, uuid4

from cloud.ingestion.object_store import StoredObject


class LocalBasicPdfStore:
    def __init__(self, object_store) -> None:
        self._object_store = object_store

    async def put(self, tenant_id: UUID, session_id: UUID, payload: bytes) -> StoredObject:
        key = f"tenants/{tenant_id}/sessions/{session_id}/basic-report-copies/{uuid4()}.pdf"
        return await self._object_store.put_report_pdf(key, payload)

    async def read(self, object_key: str) -> bytes:
        return await self._object_store.read(object_key)

    async def delete(self, object_key: str) -> None:
        await self._object_store.delete(object_key)
