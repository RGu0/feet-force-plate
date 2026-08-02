from __future__ import annotations

import hashlib
import unittest
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from httpx import ASGITransport, AsyncClient

from cloud.access_control.platform_service import PlatformProvisioningService
from cloud.access_control.repository import InMemoryAccessRepository
from cloud.access_control.tenant_service import TenantAuthenticationService
from cloud.api.access_auth import (
    LicenseDocumentSigner,
    PlatformAccessContext,
    RefreshTokenFactory,
    TenantAccessTokenIssuer,
)
from cloud.api.app import ServiceContainer, create_app
from cloud.api.auth import TerminalTokenIssuer
from cloud.api.repository import InMemoryPlatformRepository
from cloud.api.subject_service import IdentityProtector, SubjectConsentService
from cloud.device_management.service import DeviceManagementService
from cloud.ingestion.object_store import InMemoryObjectStore
from cloud.ingestion.service import IngestionService
from shared.contracts.access_control import (
    ActivateAccountRequest,
    LicenseControlAction,
    LicenseControlRequest,
    PlatformRole,
    ProvisionTenantRequest,
    RefreshRequest,
)
from shared.contracts.client_sync import canonical_sha256, encode_segment_metadata
from shared.contracts.cloud import (
    ConsentCreateRequest,
    ExternalIdentifierInput,
    ManifestSegment,
    MissingValueState,
    ProfileValue,
    HeartbeatDevice,
    HeartbeatHealth,
    HeartbeatRequest,
    HeartbeatSync,
    SegmentMetadata,
    SessionCreateRequest,
    SessionManifest,
    SessionVersions,
    SubjectCreateRequest,
    TestProtocol as ProtocolContract,
)


class TenantAccessIngestionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.now = datetime.now(UTC)
        self.access_repository = InMemoryAccessRepository()
        private_key = Ed25519PrivateKey.generate()
        public_key = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        signer = LicenseDocumentSigner(
            private_key=private_key,
            key_id="license/2-key-1",
            public_keys={"license/2-key-1": public_key},
        )
        self.tenant_tokens = TenantAccessTokenIssuer(
            secret=b"tenant-token-secret-must-be-at-least-32-bytes",
            key_id="tenant/1",
        )
        self.tenant_access = TenantAuthenticationService(
            self.access_repository,
            login_lookup_hmac_key=b"login-lookup-key-must-contain-32-bytes",
            activation_hmac_key=b"activation-key-must-contain-at-least-32-bytes",
            tenant_tokens=self.tenant_tokens,
            refresh_tokens=RefreshTokenFactory(
                digest_key=b"refresh-digest-key-must-be-at-least-32-bytes"
            ),
            license_signer=signer,
            now=lambda: self.now,
        )
        self.platform = PlatformProvisioningService(
            self.access_repository,
            login_lookup_hmac_key=b"login-lookup-key-must-contain-32-bytes",
            activation_hmac_key=b"activation-key-must-contain-at-least-32-bytes",
            license_signer=signer,
            now=lambda: self.now,
        )
        self.operator = PlatformAccessContext(
            platform_identity_id=uuid4(),
            roles=frozenset({PlatformRole.OPERATIONS}),
            token_version=1,
            expires_at=self.now + timedelta(minutes=15),
        )
        self.provisioned = await self.platform.provision_tenant(
            self.operator,
            ProvisionTenantRequest(
                tenant_name="Seed Clinic",
                account_name="seed-clinic",
                hardware_id="usb-serial-0123456789abcdef0123",
                license_period_months=12,
            ),
        )
        self.installation_id = uuid4()
        self.session = await self.tenant_access.activate(
            ActivateAccountRequest(
                account_name=self.provisioned.account_name,
                activation_code=self.provisioned.activation_code,
                password="correct-horse-battery-staple",
                password_confirmation="correct-horse-battery-staple",
                hardware_id=self.provisioned.hardware_id,
                client_installation_id=self.installation_id,
            ),
            source_fingerprint=b"tenant-ingestion-test",
        )

        group = await self.access_repository.access_group_for_license(
            self.provisioned.license_id
        )
        hardware = await self.access_repository.hardware(group.hardware_id)
        self.device_id = hardware.hardware_id
        self.site_id = uuid4()
        self.subject_id = uuid4()
        self.consent_id = uuid4()
        self.session_id = uuid4()
        self.data_repository = InMemoryPlatformRepository()
        # Compatibility/audit records only. License authority remains in the access repository.
        self.data_repository.add_terminal(
            self.provisioned.tenant_id,
            self.site_id,
            self.installation_id,
        )
        self.data_repository.add_device(
            self.provisioned.tenant_id,
            self.device_id,
            hardware.model,
        )
        self.data_repository.bind_terminal_device(
            self.provisioned.tenant_id,
            self.installation_id,
            self.device_id,
            self.now,
        )
        ingestion = IngestionService(
            self.data_repository,
            InMemoryObjectStore(),
            supported_payload_schemas={"raw-segment/1"},
            supported_manifest_schemas={"session-manifest/1"},
        )
        subjects = SubjectConsentService(
            self.data_repository,
            IdentityProtector(
                encryption_key=b"e" * 32,
                lookup_hmac_key=b"h" * 32,
                key_version="identity/1",
            ),
        )
        devices = DeviceManagementService(
            self.data_repository,
            TerminalTokenIssuer(
                secret=b"legacy-terminal-token-secret-at-least-32-bytes",
                key_id="terminal/legacy-test",
                token_ttl=timedelta(minutes=15),
            ),
            activation_code_hmac_key=b"legacy-activation-key-at-least-32-bytes",
            now=lambda: self.now,
        )
        app = create_app(
            ServiceContainer(
                ingestion=ingestion,
                subjects=subjects,
                devices=devices,
                tenant_access=self.tenant_access,
                tenant_tokens=self.tenant_tokens,
            )
        )
        self.client = AsyncClient(
            transport=ASGITransport(app=app),
            base_url="https://cloud.test",
        )

    async def asyncTearDown(self) -> None:
        await self.client.aclose()

    @staticmethod
    def headers(token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "X-Correlation-ID": str(uuid4()),
        }

    def session_request(self, session_id: UUID) -> SessionCreateRequest:
        return SessionCreateRequest(
            session_id=session_id,
            subject_uuid=self.subject_id,
            consent_record_id=self.consent_id,
            site_id=self.site_id,
            terminal_id=self.installation_id,
            device_id=self.device_id,
            test_protocol=ProtocolContract(id="standard-screening", version="1.0"),
            versions=SessionVersions(
                app="0.1.0",
                protocol_profile="do-p4864/1",
                payload_schema="raw-segment/1",
                calibration="calibration/1",
            ),
            started_at=self.now,
        )

    async def create_session(self, token: str, session_id: UUID):
        headers = self.headers(token)
        headers["Idempotency-Key"] = f"create-{session_id}"
        return await self.client.post(
            "/v1/sessions",
            headers=headers,
            json=self.session_request(session_id).model_dump(mode="json"),
        )

    async def create_subject_and_consent(self, token: str) -> None:
        subject_headers = self.headers(token)
        subject_headers["Idempotency-Key"] = "create-seed-subject"
        subject = SubjectCreateRequest(
            subject_uuid=self.subject_id,
            external_identifier=ExternalIdentifierInput(
                issuer="seed-clinic",
                id_type="medical_record_number",
                external_id="SEED-001",
            ),
            analysis_profile={
                "height_cm": ProfileValue(
                    state=MissingValueState.PROVIDED,
                    value=168.0,
                )
            },
        )
        created = await self.client.post(
            "/v1/subjects",
            headers=subject_headers,
            json=subject.model_dump(mode="json"),
        )
        self.assertEqual(created.status_code, 201, created.text)

        consent_headers = self.headers(token)
        consent_headers["Idempotency-Key"] = "create-seed-consent"
        consent = ConsentCreateRequest(
            consent_record_id=self.consent_id,
            subject_uuid=self.subject_id,
            policy_version="privacy-policy/1.0",
            purpose_codes=("SCREENING_SERVICE",),
            data_categories=("PRESSURE_RAW", "ANALYSIS_PROFILE"),
            granted_at=self.now,
            evidence_type="OPERATOR_CONFIRMED",
            terminal_signature="signed-client-evidence",
        )
        granted = await self.client.post(
            "/v1/consents",
            headers=consent_headers,
            json=consent.model_dump(mode="json"),
        )
        self.assertEqual(granted.status_code, 201, granted.text)

    async def test_suspension_blocks_new_test_but_existing_upload_continues(self) -> None:
        await self.create_subject_and_consent(self.session.access_token)
        created = await self.create_session(self.session.access_token, self.session_id)
        self.assertEqual(created.status_code, 201, created.text)

        await self.platform.control_license(
            self.operator,
            self.provisioned.license_id,
            LicenseControlRequest(
                action=LicenseControlAction.SUSPEND,
                reason_code="CUSTOMER_REQUEST",
            ),
        )
        refreshed = await self.tenant_access.refresh(
            RefreshRequest(
                refresh_token=self.session.refresh_token,
                client_installation_id=self.installation_id,
            )
        )
        self.assertFalse(refreshed.capabilities.allow_new_test)
        self.assertTrue(refreshed.capabilities.allow_upload)

        rejected = await self.create_session(refreshed.access_token, uuid4())
        self.assertEqual(rejected.status_code, 403, rejected.text)

        payload = b"captured before suspension"
        metadata = SegmentMetadata(
            segment_index=0,
            start_frame_index=0,
            frame_count=10,
            start_monotonic_ns=100,
            end_monotonic_ns=200,
            compression="zstd",
            cipher="aes-256-gcm",
            size_bytes=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(),
            payload_schema_version="raw-segment/1",
        )
        headers = self.headers(refreshed.access_token)
        headers.update(
            {
                "X-Content-SHA256": metadata.sha256,
                "X-Schema-Version": metadata.payload_schema_version,
                "X-Segment-Metadata": encode_segment_metadata(metadata),
                "Content-Type": "application/vnd.feetforceplate.segment.v1+octet-stream",
            }
        )
        uploaded = await self.client.put(
            f"/v1/sessions/{self.session_id}/segments/0",
            headers=headers,
            content=payload,
        )
        self.assertEqual(uploaded.status_code, 201, uploaded.text)

        manifest = SessionManifest(
            segment_count=1,
            total_frames=metadata.frame_count,
            total_bytes=metadata.size_bytes,
            segments=(
                ManifestSegment(
                    index=metadata.segment_index,
                    sha256=metadata.sha256,
                    size_bytes=metadata.size_bytes,
                    frame_count=metadata.frame_count,
                ),
            ),
            ended_at=self.now + timedelta(seconds=1),
            local_quality_outcome="VALID",
        )
        complete_headers = self.headers(refreshed.access_token)
        complete_headers.update(
            {
                "Idempotency-Key": "complete-suspended-session",
                "X-Content-SHA256": canonical_sha256(manifest),
                "X-Schema-Version": manifest.schema_version,
            }
        )
        completed = await self.client.post(
            f"/v1/sessions/{self.session_id}/complete",
            headers=complete_headers,
            json=manifest.model_dump(mode="json"),
        )
        self.assertEqual(completed.status_code, 200, completed.text)

    async def test_tenant_token_requires_its_own_installation_audit_identity(self) -> None:
        alien_installation = uuid4()
        alien_token = self.tenant_tokens.issue(
            tenant_id=self.provisioned.tenant_id,
            account_id=self.session.account_id,
            license_id=self.session.license_id,
            hardware_id=self.session.hardware_id,
            client_installation_id=alien_installation,
            token_version=1,
            capabilities=self.session.capabilities,
            now=self.now,
        )

        response = await self.create_session(alien_token, uuid4())

        self.assertEqual(response.status_code, 403, response.text)
        self.assertNotIn(alien_token, response.text)

    async def test_tenant_access_token_records_heartbeat_for_its_installation(self) -> None:
        headers = self.headers(self.session.access_token)
        headers.update(
            {
                "X-Terminal-ID": str(self.installation_id),
                "Idempotency-Key": "seed-heartbeat-1",
            }
        )
        heartbeat = HeartbeatRequest(
            app_version="0.1.0",
            config_version="seed/1",
            protocol_version="do-p4864/1",
            device=HeartbeatDevice(
                device_id=self.device_id,
                model="DO-P4864",
                connection_state="READY",
            ),
            sync=HeartbeatSync(
                last_successful_sync=self.now,
                pending_sessions=0,
                pending_bytes=0,
            ),
            health=HeartbeatHealth(
                disk_free_bytes=1_000_000,
                clock_skew_seconds=0.0,
            ),
            observed_at=self.now,
        )

        response = await self.client.post(
            f"/v1/terminals/{self.installation_id}/heartbeats",
            headers=headers,
            json=heartbeat.model_dump(mode="json"),
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["data"]["terminal_id"], str(self.installation_id))
