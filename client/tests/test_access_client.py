from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx

from client.cloud.access_client import (
    AccessAuthenticationFailed,
    AccessConflict,
    AccessDenied,
    CloudAccessClient,
)
from shared.contracts.access_control import (
    ActivateAccountRequest,
    HardwareLeaseRequest,
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
)


class CloudAccessClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime.now(UTC)
        self.tenant_id = uuid4()
        self.account_id = uuid4()
        self.license_id = uuid4()
        self.installation_id = uuid4()
        self.lease_id = uuid4()
        self.hardware_id = "usb-serial-0123456789abcdef0123"
        self.requests: list[httpx.Request] = []

    def response_data(self, data: dict, status_code: int = 200) -> httpx.Response:
        return httpx.Response(
            status_code,
            json={
                "data": data,
                "meta": {"server_time": self.now.isoformat().replace("+00:00", "Z")},
            },
        )

    def signed_license(self) -> dict:
        return {
            "document": {
                "tenant_id": str(self.tenant_id),
                "account_id": str(self.account_id),
                "license_id": str(self.license_id),
                "hardware_id": self.hardware_id,
                "status": "ACTIVE",
                "issued_at": self.now.isoformat(),
                "valid_from": self.now.isoformat(),
                "valid_until": (self.now + timedelta(days=365)).isoformat(),
                "version": 1,
                "enabled_features": ["reports.view", "screening.start", "sync.upload"],
                "schema_version": "license/2",
            },
            "key_id": "license/2-key-1",
            "signature": "A" * 86,
        }

    def session_data(self, *, account_state: bool = True) -> dict:
        result = {
            "tenant_id": str(self.tenant_id),
            "account_id": str(self.account_id),
            "license_id": str(self.license_id),
            "hardware_id": self.hardware_id,
            "client_installation_id": str(self.installation_id),
            "access_token": "access-token-value-at-least-20-chars",
            "access_token_expires_at": (self.now + timedelta(minutes=15)).isoformat(),
            "refresh_token": "refresh-token-value-at-least-20-chars",
            "refresh_idle_expires_at": (self.now + timedelta(days=30)).isoformat(),
            "refresh_absolute_expires_at": (self.now + timedelta(days=180)).isoformat(),
            "signed_license": self.signed_license(),
            "capabilities": {
                "allow_new_test": True,
                "allow_upload": True,
                "allow_report_view": True,
            },
        }
        if account_state:
            result["account_state"] = "ACTIVE"
        return result

    def lease_data(self) -> dict:
        return {
            "lease_id": str(self.lease_id),
            "hardware_id": self.hardware_id,
            "client_installation_id": str(self.installation_id),
            "acquired_at": self.now.isoformat(),
            "expires_at": (self.now + timedelta(minutes=10)).isoformat(),
        }

    def client(self, handler) -> CloudAccessClient:
        return CloudAccessClient(
            "https://cloud.test",
            transport=httpx.MockTransport(handler),
        )

    def test_exact_access_and_lease_calls(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            if request.url.path == "/v1/access/license":
                return self.response_data(self.signed_license())
            if request.url.path.startswith("/v1/access/hardware-lease"):
                return self.response_data(self.lease_data(), 201)
            if request.url.path == "/v1/access/logout":
                return self.response_data({"logged_out": True})
            return self.response_data(
                self.session_data(account_state=request.url.path != "/v1/access/refresh"),
                201 if request.url.path == "/v1/access/activate" else 200,
            )

        client = self.client(handler)
        activation = ActivateAccountRequest(
            account_name="seed-clinic",
            activation_code="activation-code-value-at-least-20",
            password="correct-horse-battery-staple",
            password_confirmation="correct-horse-battery-staple",
            hardware_id=self.hardware_id,
            client_installation_id=self.installation_id,
        )
        client.activate(activation)
        client.login(
            LoginRequest(
                account_name="seed-clinic",
                password="correct-horse-battery-staple",
                client_installation_id=self.installation_id,
            )
        )
        client.refresh(
            RefreshRequest(
                refresh_token="refresh-token-value-at-least-20-chars",
                client_installation_id=self.installation_id,
            )
        )
        client.fetch_license("access-token-value-at-least-20-chars")
        lease_request = HardwareLeaseRequest(
            hardware_id=self.hardware_id,
            client_installation_id=self.installation_id,
        )
        client.acquire_hardware_lease("access-token-value-at-least-20-chars", lease_request)
        client.renew_hardware_lease("access-token-value-at-least-20-chars", self.lease_id)
        client.release_hardware_lease("access-token-value-at-least-20-chars", self.lease_id)
        client.logout(LogoutRequest(refresh_token="refresh-token-value-at-least-20-chars"))

        self.assertEqual(
            [(request.method, request.url.path) for request in self.requests],
            [
                ("POST", "/v1/access/activate"),
                ("POST", "/v1/access/login"),
                ("POST", "/v1/access/refresh"),
                ("GET", "/v1/access/license"),
                ("POST", "/v1/access/hardware-lease"),
                ("PUT", f"/v1/access/hardware-lease/{self.lease_id}"),
                ("DELETE", f"/v1/access/hardware-lease/{self.lease_id}"),
                ("POST", "/v1/access/logout"),
            ],
        )
        self.assertTrue(all("X-Correlation-ID" in item.headers for item in self.requests))
        self.assertEqual(client.last_server_time, self.now)
        client.close()

    def test_safe_error_mapping_does_not_copy_server_secrets(self) -> None:
        secret = "activation-code-secret-must-not-leak"

        for status, expected in (
            (401, AccessAuthenticationFailed),
            (403, AccessDenied),
            (409, AccessConflict),
        ):
            with self.subTest(status=status):
                client = self.client(
                    lambda _request, status=status: httpx.Response(
                        status,
                        text=f"password={secret}; Authorization=Bearer {secret}",
                    )
                )
                with self.assertRaises(expected) as caught:
                    client.login(
                        LoginRequest(
                            account_name="seed-clinic",
                            password="correct-horse-battery-staple",
                            client_installation_id=self.installation_id,
                        )
                    )
                self.assertNotIn(secret, str(caught.exception))
                self.assertNotIn("Authorization", str(caught.exception))
                client.close()


if __name__ == "__main__":
    unittest.main()
