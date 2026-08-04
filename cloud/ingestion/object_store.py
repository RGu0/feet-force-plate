from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path
import tempfile
from dataclasses import dataclass
from typing import AsyncIterable, Protocol
from uuid import UUID, uuid4

from botocore.exceptions import ClientError

from cloud.api.errors import DigestMismatch, SegmentDigestConflict, SizeMismatch
from shared.contracts.client_sync import canonical_json_bytes
from shared.contracts.cloud import SegmentMetadata, SessionManifest


@dataclass(frozen=True, slots=True)
class StoredObject:
    object_key: str
    sha256: str
    size_bytes: int


class ObjectStore(Protocol):
    async def put_segment(
        self,
        tenant_id: UUID,
        session_id: UUID,
        metadata: SegmentMetadata,
        chunks: AsyncIterable[bytes],
    ) -> StoredObject: ...

    async def put_manifest(
        self,
        tenant_id: UUID,
        session_id: UUID,
        manifest: SessionManifest,
        expected_sha256: str,
    ) -> StoredObject: ...

    async def delete(self, object_key: str) -> None: ...


async def _verified_bytes(
    chunks: AsyncIterable[bytes], expected_sha256: str, expected_size: int
) -> bytes:
    digest = hashlib.sha256()
    payload = bytearray()
    async for chunk in chunks:
        digest.update(chunk)
        payload.extend(chunk)
    actual_size = len(payload)
    actual_sha256 = digest.hexdigest()
    if actual_size != expected_size:
        raise SizeMismatch("分段长度与声明不一致", expected=expected_size, actual=actual_size)
    if actual_sha256 != expected_sha256:
        raise DigestMismatch("分段摘要与声明不一致", expected=expected_sha256, actual=actual_sha256)
    return bytes(payload)


class InMemoryObjectStore:
    def __init__(self) -> None:
        self._objects: dict[str, bytes] = {}

    @property
    def object_count(self) -> int:
        return len(self._objects)

    async def put_segment(
        self,
        tenant_id: UUID,
        session_id: UUID,
        metadata: SegmentMetadata,
        chunks: AsyncIterable[bytes],
    ) -> StoredObject:
        payload = await _verified_bytes(chunks, metadata.sha256, metadata.size_bytes)
        object_key = (
            f"tenants/{tenant_id}/sessions/{session_id}/segments/"
            f"{metadata.segment_index}-{metadata.sha256}.ffps"
        )
        existing = self._objects.get(object_key)
        if existing is not None and existing != payload:
            raise SegmentDigestConflict("不可变对象键已存在不同内容", object_key=object_key)
        self._objects[object_key] = payload
        return StoredObject(object_key, metadata.sha256, metadata.size_bytes)

    async def put_manifest(
        self,
        tenant_id: UUID,
        session_id: UUID,
        manifest: SessionManifest,
        expected_sha256: str,
    ) -> StoredObject:
        payload = canonical_json_bytes(manifest)
        actual_sha256 = hashlib.sha256(payload).hexdigest()
        if actual_sha256 != expected_sha256:
            raise DigestMismatch(
                "最终清单摘要与规范化内容不一致",
                expected=expected_sha256,
                actual=actual_sha256,
            )
        object_key = (
            f"tenants/{tenant_id}/sessions/{session_id}/manifests/{expected_sha256}.json"
        )
        existing = self._objects.get(object_key)
        if existing is not None and existing != payload:
            raise SegmentDigestConflict("不可变清单对象键已存在不同内容", object_key=object_key)
        self._objects[object_key] = payload
        return StoredObject(object_key, expected_sha256, len(payload))

    async def delete(self, object_key: str) -> None:
        self._objects.pop(object_key, None)

    async def read(self, object_key: str) -> bytes:
        return self._objects[object_key]


class FileSystemObjectStore:
    """Private immutable filesystem storage with verified atomic publication."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self._staging = self.root / ".staging"
        self._mkdir_private(self.root)
        self._mkdir_private(self._staging)

    @staticmethod
    def _mkdir_private(path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            path.chmod(0o700)
        except OSError:
            pass

    def _path(self, object_key: str) -> Path:
        key_path = Path(object_key)
        if (
            not object_key
            or object_key.startswith(("/", "\\"))
            or ".." in key_path.parts
            or "\\" in object_key
        ):
            raise ValueError("object key must be relative")
        candidate = (self.root / key_path).resolve()
        if not candidate.is_relative_to(self.root) or candidate == self.root:
            raise ValueError("object key escapes storage root")
        return candidate

    async def put_segment(
        self,
        tenant_id: UUID,
        session_id: UUID,
        metadata: SegmentMetadata,
        chunks: AsyncIterable[bytes],
    ) -> StoredObject:
        object_key = (
            f"tenants/{tenant_id}/sessions/{session_id}/segments/"
            f"{metadata.segment_index}-{metadata.sha256}.ffps"
        )
        return await self._write_stream(
            object_key,
            chunks,
            expected_sha256=metadata.sha256,
            expected_size=metadata.size_bytes,
            kind="分段",
        )

    async def put_manifest(
        self,
        tenant_id: UUID,
        session_id: UUID,
        manifest: SessionManifest,
        expected_sha256: str,
    ) -> StoredObject:
        payload = canonical_json_bytes(manifest)

        async def chunks():
            yield payload

        object_key = (
            f"tenants/{tenant_id}/sessions/{session_id}/manifests/"
            f"{expected_sha256}.json"
        )
        return await self._write_stream(
            object_key,
            chunks(),
            expected_sha256=expected_sha256,
            expected_size=len(payload),
            kind="最终清单",
        )

    async def _write_stream(
        self,
        object_key: str,
        chunks: AsyncIterable[bytes],
        *,
        expected_sha256: str,
        expected_size: int,
        kind: str,
    ) -> StoredObject:
        final_path = self._path(object_key)
        self._mkdir_private(final_path.parent)
        staging_path = self._staging / f"{uuid4()}.part"
        digest = hashlib.sha256()
        size = 0
        try:
            descriptor = os.open(staging_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                async for chunk in chunks:
                    handle.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)
                handle.flush()
                os.fsync(handle.fileno())
            actual_sha256 = digest.hexdigest()
            if size != expected_size:
                raise SizeMismatch(
                    f"{kind}长度与声明不一致",
                    expected=expected_size,
                    actual=size,
                )
            if actual_sha256 != expected_sha256:
                raise DigestMismatch(
                    f"{kind}摘要与声明不一致",
                    expected=expected_sha256,
                    actual=actual_sha256,
                )
            if final_path.exists():
                self._verify_existing(
                    final_path,
                    expected_sha256=expected_sha256,
                    expected_size=expected_size,
                    object_key=object_key,
                )
                return StoredObject(object_key, expected_sha256, expected_size)
            os.replace(staging_path, final_path)
            final_path.chmod(0o600)
            if os.name != "nt":
                directory_fd = os.open(final_path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            return StoredObject(object_key, expected_sha256, expected_size)
        finally:
            try:
                staging_path.unlink()
            except FileNotFoundError:
                pass

    @staticmethod
    def _verify_existing(
        path: Path,
        *,
        expected_sha256: str,
        expected_size: int,
        object_key: str,
    ) -> None:
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
        if size != expected_size or digest.hexdigest() != expected_sha256:
            raise SegmentDigestConflict(
                "不可变对象键已存在不同内容",
                object_key=object_key,
            )

    async def delete(self, object_key: str) -> None:
        path = self._path(object_key)
        try:
            path.unlink()
        except FileNotFoundError:
            pass

    async def read(self, object_key: str) -> bytes:
        return self._path(object_key).read_bytes()


class S3ObjectStore:
    """S3-compatible immutable object adapter with KMS server-side encryption."""

    def __init__(self, client, bucket: str, kms_key_id: str) -> None:
        self._client = client
        self._bucket = bucket
        self._kms_key_id = kms_key_id

    async def put_segment(
        self,
        tenant_id: UUID,
        session_id: UUID,
        metadata: SegmentMetadata,
        chunks: AsyncIterable[bytes],
    ) -> StoredObject:
        with tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024) as handle:
            digest = hashlib.sha256()
            size = 0
            async for chunk in chunks:
                handle.write(chunk)
                digest.update(chunk)
                size += len(chunk)
            actual_sha256 = digest.hexdigest()
            if size != metadata.size_bytes:
                raise SizeMismatch("分段长度与声明不一致", expected=metadata.size_bytes, actual=size)
            if actual_sha256 != metadata.sha256:
                raise DigestMismatch(
                    "分段摘要与声明不一致", expected=metadata.sha256, actual=actual_sha256
                )
            handle.seek(0)
            final_key = (
                f"tenants/{tenant_id}/sessions/{session_id}/segments/"
                f"{metadata.segment_index}-{metadata.sha256}.ffps"
            )
            temporary_key = f"_staging/{tenant_id}/{session_id}/{uuid4()}"
            args = {
                "ServerSideEncryption": "aws:kms",
                "SSEKMSKeyId": self._kms_key_id,
                "ContentType": "application/vnd.feetforceplate.segment.v1+octet-stream",
                "Metadata": {"sha256": metadata.sha256, "schema-version": metadata.payload_schema_version},
            }
            await asyncio.to_thread(
                self._client.upload_fileobj,
                handle,
                self._bucket,
                temporary_key,
                ExtraArgs=args,
            )
            await self._commit_immutable(temporary_key, final_key, metadata.sha256, args)
            return StoredObject(final_key, metadata.sha256, size)

    async def _commit_immutable(
        self, temporary_key: str, final_key: str, sha256: str, args: dict[str, str | dict[str, str]]
    ) -> None:
        try:
            head = await asyncio.to_thread(self._client.head_object, Bucket=self._bucket, Key=final_key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") not in ("404", "NoSuchKey", "NotFound"):
                raise
        else:
            if head.get("Metadata", {}).get("sha256") != sha256:
                raise SegmentDigestConflict("不可变对象键已存在不同摘要", object_key=final_key)
            await asyncio.to_thread(self._client.delete_object, Bucket=self._bucket, Key=temporary_key)
            return
        copy_args = {
            "Bucket": self._bucket,
            "Key": final_key,
            "CopySource": {"Bucket": self._bucket, "Key": temporary_key},
            "MetadataDirective": "REPLACE",
            "Metadata": args["Metadata"],
            "ContentType": args["ContentType"],
            "ServerSideEncryption": "aws:kms",
            "SSEKMSKeyId": self._kms_key_id,
        }
        await asyncio.to_thread(self._client.copy_object, **copy_args)
        await asyncio.to_thread(self._client.delete_object, Bucket=self._bucket, Key=temporary_key)

    async def put_manifest(
        self,
        tenant_id: UUID,
        session_id: UUID,
        manifest: SessionManifest,
        expected_sha256: str,
    ) -> StoredObject:
        payload = canonical_json_bytes(manifest)
        actual_sha256 = hashlib.sha256(payload).hexdigest()
        if actual_sha256 != expected_sha256:
            raise DigestMismatch(
                "最终清单摘要与规范化内容不一致",
                expected=expected_sha256,
                actual=actual_sha256,
            )
        key = f"tenants/{tenant_id}/sessions/{session_id}/manifests/{expected_sha256}.json"
        temporary_key = f"_staging/{tenant_id}/{session_id}/{uuid4()}"
        await asyncio.to_thread(
            self._client.put_object,
            Bucket=self._bucket,
            Key=temporary_key,
            Body=payload,
            ContentType="application/json",
            Metadata={"sha256": expected_sha256, "schema-version": manifest.schema_version},
            ServerSideEncryption="aws:kms",
            SSEKMSKeyId=self._kms_key_id,
        )
        await self._commit_immutable(
            temporary_key,
            key,
            expected_sha256,
            {
                "Metadata": {"sha256": expected_sha256, "schema-version": manifest.schema_version},
                "ContentType": "application/json",
            },
        )
        return StoredObject(key, expected_sha256, len(payload))

    async def delete(self, object_key: str) -> None:
        await asyncio.to_thread(self._client.delete_object, Bucket=self._bucket, Key=object_key)
