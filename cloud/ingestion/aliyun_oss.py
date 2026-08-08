"""Alibaba Cloud OSS adapter for immutable tenant raw objects."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
from types import SimpleNamespace
from typing import AsyncIterable, Callable, Protocol
from uuid import UUID

from cloud.api.errors import DigestMismatch, SegmentDigestConflict
from shared.contracts.client_sync import canonical_json_bytes
from shared.contracts.cloud import SegmentMetadata, SessionManifest

from .object_store import StoredObject, _verified_bytes


@dataclass(frozen=True, slots=True)
class OSSHead:
    size_bytes: int
    metadata: dict[str, str]
    server_side_encryption: str | None


class OSSObjectAlreadyExists(Exception):
    """Raised when an atomic OSS create finds an existing immutable key."""


class OSSObjectNotFound(Exception):
    """Raised when an OSS object head request finds no current object."""


class OSSGateway(Protocol):
    def put_immutable(
        self,
        *,
        key: str,
        body: bytes,
        content_type: str,
        metadata: dict[str, str],
        server_side_encryption: str,
    ) -> None: ...

    def head(self, key: str) -> OSSHead: ...

    def delete(self, key: str) -> None: ...

    def check_ready(self) -> None: ...


class AliyunOSSSDKGateway:
    """Small synchronous boundary around OSS SDK V2 request objects."""

    def __init__(self, client: object, sdk: object, *, bucket: str) -> None:
        if not bucket.strip():
            raise ValueError("OSS bucket is required")
        self._client = client
        self._sdk = sdk
        self._bucket = bucket

    def put_immutable(
        self,
        *,
        key: str,
        body: bytes,
        content_type: str,
        metadata: dict[str, str],
        server_side_encryption: str,
    ) -> None:
        request = self._sdk.PutObjectRequest(
            bucket=self._bucket,
            key=key,
            body=body,
            content_type=content_type,
            metadata=metadata,
            forbid_overwrite=True,
            server_side_encryption=server_side_encryption,
        )
        try:
            self._client.put_object(request)
        except (self._sdk.ServiceError, self._sdk.OperationError) as exc:
            service_error = self._service_error(exc)
            if (
                service_error is not None
                and service_error.status_code == 409
                and service_error.code in {"FileAlreadyExists", "ObjectAlreadyExists"}
            ):
                raise OSSObjectAlreadyExists(key) from exc
            raise

    def head(self, key: str) -> OSSHead:
        try:
            result = self._client.head_object(
                self._sdk.HeadObjectRequest(bucket=self._bucket, key=key)
            )
        except (self._sdk.ServiceError, self._sdk.OperationError) as exc:
            service_error = self._service_error(exc)
            if (
                service_error is not None
                and service_error.status_code == 404
                and service_error.code in {"NoSuchKey", "NoSuchObject"}
            ):
                raise OSSObjectNotFound(key) from exc
            raise
        return OSSHead(
            size_bytes=result.content_length,
            metadata=dict(result.metadata or {}),
            server_side_encryption=result.server_side_encryption,
        )

    def delete(self, key: str) -> None:
        self._client.delete_object(
            self._sdk.DeleteObjectRequest(bucket=self._bucket, key=key)
        )

    def check_ready(self) -> None:
        self._client.get_bucket_info(
            self._sdk.GetBucketInfoRequest(bucket=self._bucket)
        )

    def _service_error(self, exc: Exception) -> object | None:
        if isinstance(exc, self._sdk.ServiceError):
            return exc
        unwrapped = exc.unwrap()
        if isinstance(unwrapped, self._sdk.ServiceError):
            return unwrapped
        return None


class AliyunOSSObjectStore:
    """Content-addressed OSS store with version-aware idempotent publication."""

    def __init__(self, gateway: OSSGateway, *, server_side_encryption: str) -> None:
        if server_side_encryption not in {"KMS", "AES256"}:
            raise ValueError("OSS server-side encryption must be KMS or AES256")
        self._gateway = gateway
        self._server_side_encryption = server_side_encryption

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
        await self._put_immutable(
            object_key,
            payload,
            content_type="application/vnd.feetforceplate.segment.v1+octet-stream",
            metadata={
                "sha256": metadata.sha256,
                "schema-version": metadata.payload_schema_version,
            },
        )
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
            f"tenants/{tenant_id}/sessions/{session_id}/manifests/"
            f"{expected_sha256}.json"
        )
        await self._put_immutable(
            object_key,
            payload,
            content_type="application/json",
            metadata={
                "sha256": expected_sha256,
                "schema-version": manifest.schema_version,
            },
        )
        return StoredObject(object_key, expected_sha256, len(payload))

    async def _put_immutable(
        self,
        object_key: str,
        payload: bytes,
        *,
        content_type: str,
        metadata: dict[str, str],
    ) -> None:
        try:
            head = await asyncio.to_thread(self._gateway.head, object_key)
        except OSSObjectNotFound:
            pass
        else:
            self._validate_existing(object_key, payload, metadata, head)
            return

        try:
            await asyncio.to_thread(
                self._gateway.put_immutable,
                key=object_key,
                body=payload,
                content_type=content_type,
                metadata=metadata,
                server_side_encryption=self._server_side_encryption,
            )
        except OSSObjectAlreadyExists:
            head = await asyncio.to_thread(self._gateway.head, object_key)
            self._validate_existing(object_key, payload, metadata, head)

    def _validate_existing(
        self,
        object_key: str,
        payload: bytes,
        metadata: dict[str, str],
        head: OSSHead,
    ) -> None:
        if (
            head.size_bytes != len(payload)
            or head.metadata.get("sha256") != metadata["sha256"]
            or head.server_side_encryption != self._server_side_encryption
        ):
            raise SegmentDigestConflict(
                "不可变 OSS 对象键已存在不同内容或安全属性",
                object_key=object_key,
            ) from None

    async def delete(self, object_key: str) -> None:
        await asyncio.to_thread(self._gateway.delete, object_key)

    async def check_ready(self) -> None:
        await asyncio.to_thread(self._gateway.check_ready)


def build_aliyun_oss_object_store(
    settings: object,
    *,
    credential_client_cls: type | None = None,
    client_factory: Callable[[object], object] | None = None,
) -> AliyunOSSObjectStore:
    """Compose OSS SDK V2 with refreshable ECS RAM-role credentials."""

    client, oss = build_aliyun_oss_sdk(
        settings,
        credential_client_cls=credential_client_cls,
        client_factory=client_factory,
    )
    bindings = SimpleNamespace(
        PutObjectRequest=oss.PutObjectRequest,
        HeadObjectRequest=oss.HeadObjectRequest,
        DeleteObjectRequest=oss.DeleteObjectRequest,
        GetBucketInfoRequest=oss.GetBucketInfoRequest,
        OperationError=oss.exceptions.OperationError,
        ServiceError=oss.exceptions.ServiceError,
    )
    gateway = AliyunOSSSDKGateway(client, bindings, bucket=settings.oss_bucket)
    return AliyunOSSObjectStore(
        gateway,
        server_side_encryption=settings.oss_server_side_encryption,
    )


def build_aliyun_oss_sdk(
    settings: object,
    *,
    credential_client_cls: type | None = None,
    client_factory: Callable[[object], object] | None = None,
) -> tuple[object, object]:
    """Build the native SDK client with refreshable ECS RAM-role credentials."""

    import alibabacloud_oss_v2 as oss
    from alibabacloud_credentials.client import Client as CredentialClient
    from alibabacloud_credentials.models import Config as CredentialConfig

    credential_config = CredentialConfig(
        type="ecs_ram_role",
        role_name=settings.oss_ecs_ram_role,
        enable_imds_v2=True,
        disable_imds_v1=True,
        metadata_token_duration=3600,
    )
    credential_client = (credential_client_cls or CredentialClient)(credential_config)

    def credentials() -> object:
        value = credential_client.get_credential()
        return oss.credentials.Credentials(
            access_key_id=value.access_key_id,
            access_key_secret=value.access_key_secret,
            security_token=value.security_token,
        )

    config = oss.config.load_default()
    config.credentials_provider = oss.credentials.CredentialsProviderFunc(
        func=credentials
    )
    config.region = settings.oss_region
    config.endpoint = settings.oss_endpoint
    client = (client_factory or oss.Client)(config)
    return client, oss


__all__ = [
    "AliyunOSSObjectStore",
    "AliyunOSSSDKGateway",
    "OSSGateway",
    "OSSHead",
    "OSSObjectAlreadyExists",
    "OSSObjectNotFound",
    "build_aliyun_oss_sdk",
    "build_aliyun_oss_object_store",
]
