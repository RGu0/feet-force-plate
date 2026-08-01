from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from httpx import ASGITransport, AsyncClient

from cloud.access_control.lease_service import HardwareLeaseService
from cloud.access_control.platform_service import PlatformProvisioningService
from cloud.access_control.repository import InMemoryAccessRepository
from cloud.access_control.tenant_service import TenantAuthenticationService
from cloud.api.access_auth import (
    LicenseDocumentSigner,
    PlatformAccessTokenIssuer,
    PlatformAccessContext,
    RefreshTokenFactory,
    TenantAccessTokenIssuer,
)
from cloud.api.app import ServiceContainer, create_app
from shared.contracts.access_control import PlatformRole, ProvisionTenantRequest


class TenantAccessApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.now = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
        repository = InMemoryAccessRepository()
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
        refresh_tokens = RefreshTokenFactory(
            digest_key=b"refresh-digest-key-must-be-at-least-32-bytes"
        )
        self.tenant_access = TenantAuthenticationService(
            repository,
            login_lookup_hmac_key=b"login-lookup-key-must-contain-32-bytes",
            activation_hmac_key=b"activation-key-must-contain-at-least-32-bytes",
            tenant_tokens=self.tenant_tokens,
            refresh_tokens=refresh_tokens,
            license_signer=signer,
            now=lambda: self.now,
        )
        platform = PlatformProvisioningService(
            repository,
            login_lookup_hmac_key=b"login-lookup-key-must-contain-32-bytes",
            activation_hmac_key=b"activation-key-must-contain-at-least-32-bytes",
            license_signer=signer,
            now=lambda: self.now,
        )
        operator = PlatformAccessContext(
            platform_identity_id=uuid4(),
            roles=frozenset({PlatformRole.OPERATIONS}),
            token_version=1,
            expires_at=self.now + timedelta(minutes=15),
        )
        self.provisioned = await platform.provision_tenant(
            operator,
            ProvisionTenantRequest(
                tenant_name="Seed Clinic",
                account_name="seed-clinic",
                hardware_id="usb-serial-0123456789abcdef0123",
                license_period_months=12,
            ),
        )
        app = create_app(
            ServiceContainer(
                tenant_access=self.tenant_access,
                tenant_tokens=self.tenant_tokens,
                hardware_leases=HardwareLeaseService(repository, now=lambda: self.now),
            )
        )
        self.client = AsyncClient(
            transport=ASGITransport(app=app),
            base_url="https://cloud.test",
        )

    async def asyncTearDown(self) -> None:
        await self.client.aclose()

    def activation_body(self) -> dict[str, str]:
        return {
            "account_name": self.provisioned.account_name,
            "activation_code": self.provisioned.activation_code,
            "password": "correct-horse-battery-staple",
            "password_confirmation": "correct-horse-battery-staple",
            "hardware_id": self.provisioned.hardware_id,
            "client_installation_id": str(uuid4()),
        }

    async def test_activate_login_refresh_license_and_lease_routes(self) -> None:
        activated = await self.client.post("/v1/access/activate", json=self.activation_body())
        self.assertEqual(activated.status_code, 201, activated.text)
        session = activated.json()["data"]
        headers = {"Authorization": f"Bearer {session['access_token']}"}

        license_response = await self.client.get("/v1/access/license", headers=headers)
        lease = await self.client.post(
            "/v1/access/hardware-lease",
            headers=headers,
            json={
                "hardware_id": session["hardware_id"],
                "client_installation_id": session["client_installation_id"],
            },
        )
        refreshed = await self.client.post(
            "/v1/access/refresh",
            json={
                "refresh_token": session["refresh_token"],
                "client_installation_id": session["client_installation_id"],
            },
        )

        self.assertEqual(license_response.status_code, 200, license_response.text)
        self.assertEqual(lease.status_code, 201, lease.text)
        self.assertEqual(refreshed.status_code, 200, refreshed.text)
        self.assertNotEqual(
            refreshed.json()["data"]["refresh_token"],
            session["refresh_token"],
        )

    async def test_platform_token_cannot_call_tenant_access_route(self) -> None:
        platform_issuer = PlatformAccessTokenIssuer(
            secret=b"platform-token-secret-must-be-at-least-32-bytes",
            key_id="platform/1",
        )
        token = platform_issuer.issue(
            platform_identity_id=uuid4(),
            roles=(PlatformRole.OWNER,),
            token_version=1,
            now=self.now,
        )

        response = await self.client.get(
            "/v1/access/license",
            headers={"Authorization": f"Bearer {token}"},
        )

        self.assertEqual(response.status_code, 401)
        self.assertNotIn(token, response.text)

    async def test_local_ui_test_license_never_reaches_cloud_activation(self) -> None:
        body = self.activation_body()
        body["activation_code"] = "FFP-2026-TEST-0001"

        response = await self.client.post("/v1/access/activate", json=body)

        self.assertIn(response.status_code, {401, 422})
        self.assertNotIn("seed-clinic", response.text)
