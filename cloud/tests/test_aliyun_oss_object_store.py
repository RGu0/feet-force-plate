from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from cloud.api.errors import SegmentDigestConflict
from cloud.ingestion.aliyun_oss import (
    AliyunOSSObjectStore,
    AliyunOSSSDKGateway,
    OSSHead,
    OSSObjectAlreadyExists,
    OSSObjectNotFound,
    build_aliyun_oss_object_store,
)
from shared.contracts.client_sync import canonical_sha256
from shared.contracts.cloud import ManifestSegment, SegmentMetadata, SessionManifest


@dataclass(frozen=True)
class _Object:
    body: bytes
    content_type: str
    metadata: dict[str, str]
    server_side_encryption: str


class _Gateway:
    def __init__(self) -> None:
        self.objects: dict[str, _Object] = {}
        self.put_attempts = 0
        self.ready_checks = 0

    def put_immutable(
        self,
        *,
        key: str,
        body: bytes,
        content_type: str,
        metadata: dict[str, str],
        server_side_encryption: str,
    ) -> None:
        self.put_attempts += 1
        if key in self.objects:
            raise OSSObjectAlreadyExists(key)
        self.objects[key] = _Object(
            body=body,
            content_type=content_type,
            metadata=dict(metadata),
            server_side_encryption=server_side_encryption,
        )

    def head(self, key: str) -> OSSHead:
        if key not in self.objects:
            raise OSSObjectNotFound(key)
        value = self.objects[key]
        return OSSHead(
            size_bytes=len(value.body),
            metadata=value.metadata,
            server_side_encryption=value.server_side_encryption,
        )

    def delete(self, key: str) -> None:
        self.objects.pop(key, None)

    def check_ready(self) -> None:
        self.ready_checks += 1


async def _chunks(payload: bytes):
    yield payload[:2]
    yield payload[2:]


def _metadata(payload: bytes, *, index: int = 0) -> SegmentMetadata:
    return SegmentMetadata(
        segment_index=index,
        start_frame_index=index,
        frame_count=1,
        start_monotonic_ns=1,
        end_monotonic_ns=2,
        compression="zstd",
        cipher="aes-256-gcm",
        payload_schema_version="raw-segment/1",
        sha256=hashlib.sha256(payload).hexdigest(),
        size_bytes=len(payload),
    )


def test_oss_segment_is_tenant_prefixed_immutable_and_kms_encrypted() -> None:
    async def exercise() -> None:
        gateway = _Gateway()
        store = AliyunOSSObjectStore(gateway, server_side_encryption="KMS")
        tenant_id = uuid4()
        session_id = uuid4()
        payload = b"raw-segment"
        metadata = _metadata(payload)

        stored = await store.put_segment(
            tenant_id, session_id, metadata, _chunks(payload)
        )

        assert stored.object_key.startswith(
            f"tenants/{tenant_id}/sessions/{session_id}/segments/0-"
        )
        uploaded = gateway.objects[stored.object_key]
        assert uploaded.body == payload
        assert uploaded.metadata == {
            "sha256": metadata.sha256,
            "schema-version": "raw-segment/1",
        }
        assert uploaded.server_side_encryption == "KMS"

    asyncio.run(exercise())


def test_oss_same_digest_replay_is_idempotent() -> None:
    async def exercise() -> None:
        gateway = _Gateway()
        store = AliyunOSSObjectStore(gateway, server_side_encryption="KMS")
        tenant_id = uuid4()
        session_id = uuid4()
        payload = b"same-segment"
        metadata = _metadata(payload)

        first = await store.put_segment(
            tenant_id, session_id, metadata, _chunks(payload)
        )
        second = await store.put_segment(
            tenant_id, session_id, metadata, _chunks(payload)
        )

        assert second == first
        assert len(gateway.objects) == 1
        assert gateway.put_attempts == 1

    asyncio.run(exercise())


def test_oss_existing_key_with_wrong_integrity_metadata_is_rejected() -> None:
    async def exercise() -> None:
        gateway = _Gateway()
        store = AliyunOSSObjectStore(gateway, server_side_encryption="KMS")
        tenant_id = uuid4()
        session_id = uuid4()
        payload = b"expected"
        metadata = _metadata(payload)
        key = (
            f"tenants/{tenant_id}/sessions/{session_id}/segments/"
            f"0-{metadata.sha256}.ffps"
        )
        gateway.objects[key] = _Object(
            body=b"different",
            content_type="application/octet-stream",
            metadata={"sha256": "0" * 64, "schema-version": "raw-segment/1"},
            server_side_encryption="KMS",
        )

        with pytest.raises(SegmentDigestConflict):
            await store.put_segment(tenant_id, session_id, metadata, _chunks(payload))
        assert gateway.put_attempts == 0

    asyncio.run(exercise())


def test_oss_readiness_delegates_to_bucket_gateway() -> None:
    async def exercise() -> None:
        gateway = _Gateway()
        store = AliyunOSSObjectStore(gateway, server_side_encryption="KMS")

        await store.check_ready()

        assert gateway.ready_checks == 1

    asyncio.run(exercise())


def test_oss_manifest_is_canonical_immutable_and_kms_encrypted() -> None:
    async def exercise() -> None:
        gateway = _Gateway()
        store = AliyunOSSObjectStore(gateway, server_side_encryption="KMS")
        tenant_id = uuid4()
        session_id = uuid4()
        payload = b"raw-segment"
        segment = _metadata(payload)
        manifest = SessionManifest(
            segment_count=1,
            total_frames=1,
            total_bytes=len(payload),
            segments=(
                ManifestSegment(
                    index=0,
                    sha256=segment.sha256,
                    size_bytes=len(payload),
                    frame_count=1,
                ),
            ),
            ended_at=datetime.now(UTC),
            local_quality_outcome="VALID",
        )
        digest = canonical_sha256(manifest)

        stored = await store.put_manifest(tenant_id, session_id, manifest, digest)

        uploaded = gateway.objects[stored.object_key]
        assert "/manifests/" in stored.object_key
        assert hashlib.sha256(uploaded.body).hexdigest() == digest
        assert uploaded.metadata == {
            "sha256": digest,
            "schema-version": "session-manifest/1",
        }
        assert uploaded.server_side_encryption == "KMS"

    asyncio.run(exercise())


class _SDK:
    class PutObjectRequest(SimpleNamespace):
        pass

    class HeadObjectRequest(SimpleNamespace):
        pass

    class DeleteObjectRequest(SimpleNamespace):
        pass

    class GetBucketInfoRequest(SimpleNamespace):
        pass

    class ServiceError(Exception):
        def __init__(self, status_code: int, code: str) -> None:
            self.status_code = status_code
            self.code = code

    class OperationError(Exception):
        def __init__(self, error: Exception) -> None:
            self._error = error

        def unwrap(self) -> Exception:
            return self._error


class _SDKClient:
    def __init__(self) -> None:
        self.put_requests: list[SimpleNamespace] = []
        self.head_result = SimpleNamespace(
            content_length=7,
            metadata={"sha256": "a" * 64},
            server_side_encryption="KMS",
        )
        self.bucket_checks = 0

    def put_object(self, request: SimpleNamespace) -> None:
        self.put_requests.append(request)

    def head_object(self, request: SimpleNamespace) -> SimpleNamespace:
        return self.head_result

    def delete_object(self, request: SimpleNamespace) -> None:
        return None

    def get_bucket_info(self, request: SimpleNamespace) -> None:
        self.bucket_checks += 1


def test_sdk_gateway_requests_atomic_kms_encrypted_private_object() -> None:
    client = _SDKClient()
    gateway = AliyunOSSSDKGateway(client, _SDK, bucket="private-raw")

    gateway.put_immutable(
        key="tenants/t/sessions/s/segments/0.ffps",
        body=b"payload",
        content_type="application/octet-stream",
        metadata={"sha256": "a" * 64},
        server_side_encryption="KMS",
    )

    request = client.put_requests[0]
    assert request.bucket == "private-raw"
    assert request.forbid_overwrite is True
    assert request.server_side_encryption == "KMS"
    assert request.metadata == {"sha256": "a" * 64}
    assert request.body == b"payload"


def test_sdk_gateway_converts_only_oss_existing_object_conflict() -> None:
    class ExistingClient(_SDKClient):
        def put_object(self, request: SimpleNamespace) -> None:
            raise _SDK.ServiceError(409, "FileAlreadyExists")

    gateway = AliyunOSSSDKGateway(ExistingClient(), _SDK, bucket="private-raw")

    with pytest.raises(OSSObjectAlreadyExists):
        gateway.put_immutable(
            key="tenants/t/sessions/s/segments/0.ffps",
            body=b"payload",
            content_type="application/octet-stream",
            metadata={"sha256": "a" * 64},
            server_side_encryption="KMS",
        )


def test_sdk_gateway_converts_wrapped_existing_object_conflict() -> None:
    class ExistingClient(_SDKClient):
        def put_object(self, request: SimpleNamespace) -> None:
            raise _SDK.OperationError(_SDK.ServiceError(409, "ObjectAlreadyExists"))

    gateway = AliyunOSSSDKGateway(ExistingClient(), _SDK, bucket="private-raw")

    with pytest.raises(OSSObjectAlreadyExists):
        gateway.put_immutable(
            key="tenants/t/sessions/s/segments/0.ffps",
            body=b"payload",
            content_type="application/octet-stream",
            metadata={"sha256": "a" * 64},
            server_side_encryption="KMS",
        )


def test_sdk_gateway_converts_wrapped_missing_head() -> None:
    class MissingClient(_SDKClient):
        def head_object(self, request: SimpleNamespace) -> SimpleNamespace:
            raise _SDK.OperationError(_SDK.ServiceError(404, "NoSuchKey"))

    gateway = AliyunOSSSDKGateway(MissingClient(), _SDK, bucket="private-raw")

    with pytest.raises(OSSObjectNotFound):
        gateway.head("tenants/t/sessions/s/segments/0.ffps")


def test_sdk_gateway_readiness_uses_bucket_info_without_listing_objects() -> None:
    client = _SDKClient()
    gateway = AliyunOSSSDKGateway(client, _SDK, bucket="private-raw")

    gateway.check_ready()

    assert client.bucket_checks == 1


def test_store_factory_uses_rotating_ecs_role_and_internal_https_endpoint() -> None:
    credential_configs: list[object] = []
    oss_configs: list[object] = []
    client = _SDKClient()

    class CredentialClient:
        def __init__(self, config: object) -> None:
            credential_configs.append(config)

        def get_credential(self) -> SimpleNamespace:
            return SimpleNamespace(
                access_key_id="STS.test",
                access_key_secret="not-printed",
                security_token="not-printed",
            )

    def client_factory(config: object) -> _SDKClient:
        oss_configs.append(config)
        credentials = config.credentials_provider.get_credentials()
        assert credentials.access_key_id == "STS.test"
        return client

    settings = SimpleNamespace(
        oss_region="us-west-1",
        oss_endpoint="https://oss-us-west-1-internal.aliyuncs.com",
        oss_bucket="private-raw",
        oss_server_side_encryption="KMS",
        oss_ecs_ram_role="feetforceplate-oss",
    )

    store = build_aliyun_oss_object_store(
        settings,
        credential_client_cls=CredentialClient,
        client_factory=client_factory,
    )
    asyncio.run(store.check_ready())

    assert credential_configs[0].type == "ecs_ram_role"
    assert credential_configs[0].role_name == "feetforceplate-oss"
    assert credential_configs[0].enable_imds_v2 is True
    assert credential_configs[0].disable_imds_v1 is True
    assert oss_configs[0].region == "us-west-1"
    assert oss_configs[0].endpoint.endswith("-internal.aliyuncs.com")
    assert client.bucket_checks == 1
