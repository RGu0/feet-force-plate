from __future__ import annotations

import unittest
from datetime import UTC, datetime
from uuid import uuid4

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from httpx import ASGITransport, AsyncClient

from cloud.access_control.platform_iam import PlatformIdentityService, SensitiveAccessService
from cloud.access_control.platform_service import PlatformProvisioningService
from cloud.access_control.repository import InMemoryAccessRepository
from cloud.access_control.tenant_service import TenantAuthenticationService
from cloud.api.access_auth import (
    LicenseDocumentSigner,
    PlatformAccessTokenIssuer,
    RefreshTokenFactory,
    TenantAccessTokenIssuer,
)
from cloud.api.app import ServiceContainer, create_app
from shared.contracts.access_control import (
    AccessCapabilities,
    ActivateAccountRequest,
    PlatformRole,
)


class PlatformApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.now = datetime.now(UTC).replace(microsecond=0)
        self.repository = InMemoryAccessRepository()
        private_key = Ed25519PrivateKey.generate()
        public_key = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        signer = LicenseDocumentSigner(
            private_key=private_key,
            key_id="license/2-key-1",
            public_keys={"license/2-key-1": public_key},
        )
        self.platform_tokens = PlatformAccessTokenIssuer(
            secret=b"platform-token-secret-must-be-at-least-32-bytes",
            key_id="platform/1",
        )
        self.identities = PlatformIdentityService(
            self.repository,
            login_lookup_hmac_key=b"platform-login-lookup-key-at-least-32-bytes",
            token_issuer=self.platform_tokens,
            refresh_tokens=RefreshTokenFactory(
                digest_key=b"platform-refresh-key-must-be-at-least-32-bytes"
            ),
            now=lambda: self.now,
        )
        self.owner_login = await self.identities.bootstrap_owner(
            login_name="platform-owner",
            display_name="Platform Owner",
            password="correct-horse-battery-staple",
        )
        self.platform_access = PlatformProvisioningService(
            self.repository,
            login_lookup_hmac_key=b"login-lookup-key-must-contain-32-bytes",
            activation_hmac_key=b"activation-key-must-contain-at-least-32-bytes",
            license_signer=signer,
            now=lambda: self.now,
        )
        self.tenant_tokens = TenantAccessTokenIssuer(
            secret=b"tenant-token-secret-must-be-at-least-32-bytes",
            key_id="tenant/1",
        )
        self.tenant_access = TenantAuthenticationService(
            self.repository,
            login_lookup_hmac_key=b"login-lookup-key-must-contain-32-bytes",
            activation_hmac_key=b"activation-key-must-contain-at-least-32-bytes",
            tenant_tokens=self.tenant_tokens,
            refresh_tokens=RefreshTokenFactory(
                digest_key=b"tenant-refresh-key-must-be-at-least-32-bytes"
            ),
            license_signer=signer,
            now=lambda: self.now,
        )
        app = create_app(
            ServiceContainer(
                platform_identities=self.identities,
                platform_access=self.platform_access,
                platform_tokens=self.platform_tokens,
                platform_sensitive=SensitiveAccessService(
                    self.repository,
                    now=lambda: self.now,
                ),
            )
        )
        self.client = AsyncClient(
            transport=ASGITransport(app=app),
            base_url="https://cloud.test",
        )
        self.owner_headers = {
            "Authorization": f"Bearer {self.owner_login.access_token}"
        }

    async def asyncTearDown(self) -> None:
        await self.client.aclose()

    def tenant_body(self) -> dict:
        return {
            "tenant_name": "Seed Clinic",
            "account_name": "seed-clinic",
            "hardware_id": "usb-serial-0123456789abcdef0123",
            "license_period_months": 12,
        }

    async def test_owner_provisions_lists_and_controls_tenant_license(self) -> None:
        created = await self.client.post(
            "/v1/platform/tenants",
            headers=self.owner_headers,
            json=self.tenant_body(),
        )
        self.assertEqual(created.status_code, 201, created.text)
        provisioned = created.json()["data"]
        await self.tenant_access.activate(
            ActivateAccountRequest(
                account_name=provisioned["account_name"],
                activation_code=provisioned["activation_code"],
                password="correct-horse-battery-staple",
                password_confirmation="correct-horse-battery-staple",
                hardware_id=provisioned["hardware_id"],
                client_installation_id=uuid4(),
            ),
            source_fingerprint=b"test-source",
        )

        listed = await self.client.get(
            "/v1/platform/tenants",
            headers=self.owner_headers,
        )
        suspended = await self.client.patch(
            f"/v1/platform/licenses/{provisioned['license_id']}",
            headers=self.owner_headers,
            json={
                "action": "SUSPEND",
                "reason_code": "CUSTOMER_REQUEST",
            },
        )
        grant = await self.client.post(
            "/v1/platform/sensitive-access-grants",
            headers=self.owner_headers,
            json={
                "tenant_id": provisioned["tenant_id"],
                "purpose_code": "SUPPORT_DIAGNOSIS",
                "ticket_reference": "SUP-100",
                "requested_duration_minutes": 15,
            },
        )

        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual(suspended.status_code, 200, suspended.text)
        self.assertEqual(grant.status_code, 201, grant.text)

    async def test_support_cannot_provision_and_tenant_token_cannot_call_platform(self) -> None:
        owner = await self.identities.verify_access_token(self.owner_login.access_token)
        support_login = await self.identities.create_identity(
            owner,
            login_name="platform-support",
            display_name="Support One",
            password="support-password-long-enough",
            roles=(PlatformRole.SUPPORT,),
        )
        support_response = await self.client.post(
            "/v1/platform/tenants",
            headers={"Authorization": f"Bearer {support_login.access_token}"},
            json=self.tenant_body(),
        )
        tenant_token = self.tenant_tokens.issue(
            tenant_id=uuid4(),
            account_id=uuid4(),
            license_id=uuid4(),
            hardware_id="usb-serial-ffffffffffffffffffff",
            client_installation_id=uuid4(),
            token_version=1,
            capabilities=AccessCapabilities(
                allow_new_test=True,
                allow_upload=True,
                allow_report_view=True,
            ),
            now=self.now,
        )
        tenant_response = await self.client.get(
            "/v1/platform/tenants",
            headers={"Authorization": f"Bearer {tenant_token}"},
        )

        self.assertEqual(support_response.status_code, 403)
        self.assertEqual(tenant_response.status_code, 401)
