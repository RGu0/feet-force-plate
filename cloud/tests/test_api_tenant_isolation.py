from __future__ import annotations

import unittest
from datetime import UTC, datetime
from uuid import uuid4

from httpx import ASGITransport, AsyncClient

from cloud.api.access_auth import TenantAccessTokenIssuer
from cloud.api.app import ServiceContainer, create_app
from cloud.api.repository import InMemoryPlatformRepository
from cloud.ingestion.object_store import InMemoryObjectStore
from cloud.ingestion.service import IngestionService
from shared.contracts.access_control import AccessCapabilities
from shared.contracts.cloud import (
    SessionCreateRequest,
    SessionVersions,
    TestProtocol as ProtocolContract,
)


class TenantAccessIsolationApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.now = datetime.now(UTC)
        self.left_tenant = uuid4()
        self.right_tenant = uuid4()
        self.left_installation = uuid4()
        self.right_installation = uuid4()
        self.site_id = uuid4()
        self.device_id = uuid4()
        self.subject_id = uuid4()
        self.consent_id = uuid4()
        self.session_id = uuid4()
        repository = InMemoryPlatformRepository()
        repository.add_terminal(
            self.left_tenant,
            self.site_id,
            self.left_installation,
        )
        repository.add_terminal(
            self.right_tenant,
            uuid4(),
            self.right_installation,
        )
        repository.add_device(self.left_tenant, self.device_id, "DO-P4864")
        repository.add_subject(self.left_tenant, self.subject_id)
        repository.add_consent(
            self.left_tenant,
            self.subject_id,
            self.consent_id,
            self.now,
        )
        issuer = TenantAccessTokenIssuer(
            secret=b"tenant-token-secret-must-be-at-least-32-bytes",
            key_id="tenant/1",
        )
        capabilities = AccessCapabilities(
            allow_new_test=True,
            allow_upload=True,
            allow_report_view=True,
        )
        self.left_token = issuer.issue(
            tenant_id=self.left_tenant,
            account_id=uuid4(),
            license_id=uuid4(),
            hardware_id="usb-serial-left0000000000000001",
            client_installation_id=self.left_installation,
            token_version=1,
            capabilities=capabilities,
            now=self.now,
        )
        self.right_token = issuer.issue(
            tenant_id=self.right_tenant,
            account_id=uuid4(),
            license_id=uuid4(),
            hardware_id="usb-serial-right000000000000001",
            client_installation_id=self.right_installation,
            token_version=1,
            capabilities=capabilities,
            now=self.now,
        )
        ingestion = IngestionService(
            repository,
            InMemoryObjectStore(),
            supported_payload_schemas={"raw-segment/1"},
            supported_manifest_schemas={"session-manifest/1"},
        )
        app = create_app(
            ServiceContainer(ingestion=ingestion, tenant_tokens=issuer)
        )
        self.client = AsyncClient(
            transport=ASGITransport(app=app),
            base_url="https://cloud.test",
        )

    async def asyncTearDown(self) -> None:
        await self.client.aclose()

    def headers(self, token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "X-Correlation-ID": str(uuid4()),
        }

    async def test_right_tenant_cannot_read_left_tenant_session(self) -> None:
        request = SessionCreateRequest(
            session_id=self.session_id,
            subject_uuid=self.subject_id,
            consent_record_id=self.consent_id,
            site_id=self.site_id,
            terminal_id=self.left_installation,
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
        left_headers = self.headers(self.left_token)
        left_headers["Idempotency-Key"] = "left-session"
        created = await self.client.post(
            "/v1/sessions",
            headers=left_headers,
            json=request.model_dump(mode="json"),
        )
        self.assertEqual(created.status_code, 201, created.text)

        denied = await self.client.get(
            f"/v1/sessions/{self.session_id}/status",
            headers=self.headers(self.right_token),
        )

        self.assertEqual(denied.status_code, 403, denied.text)
        self.assertNotIn(self.left_token, denied.text)
        self.assertNotIn(self.right_token, denied.text)


if __name__ == "__main__":
    unittest.main()
