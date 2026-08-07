from __future__ import annotations

import tempfile
import unittest
import base64
import json
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from client.cloud.access_client import AccessAuthenticationFailed
from client.cloud.access_store import ClientAccessStore
from client.cloud.hardware_identity import (
    ActivationHardwareResult,
    ActivationHardwareStatus,
)
from client.cloud.runtime import (
    AccessRuntimeSettings,
    ClientAccessRuntime,
    LicenseHardwareMismatch,
)
from client.cloud.policy import AccountHardwareLicenseVerifier
from shared.contracts.access_control import LicenseDocumentV2
from shared.contracts.client_sync import canonical_json_bytes
from shared.contracts.access_control import (
    ActivateAccountResponse,
    LoginResponse,
    RefreshResponse,
)


class MemoryCredentials:
    def __init__(self) -> None:
        self.values: dict[UUID, str] = {}

    def set_refresh_token(self, account_id: UUID, refresh_token: str) -> None:
        self.values[account_id] = refresh_token

    def get_refresh_token(self, account_id: UUID) -> str | None:
        return self.values.get(account_id)

    def delete_refresh_token(self, account_id: UUID) -> None:
        self.values.pop(account_id, None)


class FixedHardware:
    def discover(self) -> ActivationHardwareResult:
        return ActivationHardwareResult(ActivationHardwareStatus.READY)


class FakeAccessClient:
    def __init__(self, now: datetime, hardware_id: str) -> None:
        self.now = now
        self.last_server_time = now
        self.hardware_id = hardware_id
        self.tenant_id = uuid4()
        self.account_id = uuid4()
        self.license_id = uuid4()
        self.hardware_asset_id = uuid4()
        self.activation_requests = []
        self.inventory_activation_requests = []
        self.login_requests = []
        self.refresh_requests = []
        self.logout_requests = []
        self.refresh_rejected = False
        self.short_access = False
        self.private_key = Ed25519PrivateKey.generate()
        public_key = self.private_key.public_key().public_bytes(
            Encoding.Raw,
            PublicFormat.Raw,
        )
        self.verifier = AccountHardwareLicenseVerifier(
            {"license/2-key-1": public_key}
        )

    def data(self, installation_id: UUID, *, refresh_index: int = 0) -> dict:
        expires = timedelta(seconds=30) if self.short_access else timedelta(minutes=15)
        document = LicenseDocumentV2.model_validate(
            {
                "tenant_id": self.tenant_id,
                "account_id": self.account_id,
                "license_id": self.license_id,
                "hardware_id": self.hardware_id,
                "status": "ACTIVE",
                "issued_at": self.now,
                "valid_from": self.now,
                "valid_until": self.now + timedelta(days=365),
                "version": 1 + refresh_index,
                "enabled_features": [
                    "reports.view",
                    "screening.start",
                    "sync.upload",
                ],
            }
        )
        signature = base64.b64encode(
            self.private_key.sign(canonical_json_bytes(document))
        ).decode("ascii")
        return {
            "tenant_id": self.tenant_id,
            "account_id": self.account_id,
            "license_id": self.license_id,
            "hardware_asset_id": self.hardware_asset_id,
            "hardware_id": self.hardware_id,
            "client_installation_id": installation_id,
            "access_token": f"access-token-{refresh_index}-value-at-least-20",
            "access_token_expires_at": self.now + expires,
            "refresh_token": f"refresh-token-{refresh_index}-value-at-least-20",
            "refresh_idle_expires_at": self.now + timedelta(days=30),
            "refresh_absolute_expires_at": self.now + timedelta(days=180),
            "signed_license": {
                "document": document.model_dump(mode="json"),
                "key_id": "license/2-key-1",
                "signature": signature,
            },
            "capabilities": {
                "allow_new_test": True,
                "allow_upload": True,
                "allow_report_view": True,
            },
        }

    def activate(self, request):
        self.activation_requests.append(request)
        return ActivateAccountResponse.model_validate(
            {**self.data(request.client_installation_id), "account_state": "ACTIVE"}
        )

    def activate_inventory(self, request):
        self.inventory_activation_requests.append(request)
        return ActivateAccountResponse.model_validate(
            {**self.data(request.client_installation_id), "account_state": "ACTIVE"}
        )

    def login(self, request):
        self.login_requests.append(request)
        return LoginResponse.model_validate(
            {**self.data(request.client_installation_id), "account_state": "ACTIVE"}
        )

    def refresh(self, request):
        self.refresh_requests.append(request)
        if self.refresh_rejected:
            raise AccessAuthenticationFailed("rejected", status_code=401)
        self.short_access = False
        return RefreshResponse.model_validate(
            self.data(request.client_installation_id, refresh_index=len(self.refresh_requests))
        )

    def logout(self, request) -> None:
        self.logout_requests.append(request)


class ClientAccessRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.now = datetime.now(UTC)
        self.hardware_id = "FFP-DP4864-000001"
        self.credentials = MemoryCredentials()
        self.store = ClientAccessStore(
            Path(self.temp.name) / "access.sqlite3",
            self.credentials,
        )
        self.client = FakeAccessClient(self.now, self.hardware_id)
        self.installation_id = uuid4()
        self.runtime = ClientAccessRuntime(
            self.client,
            self.store,
            FixedHardware(),
            license_verifier=self.client.verifier,
            client_installation_id=self.installation_id,
            now=lambda: self.now,
            monotonic_ns=lambda: 100,
        )

    def tearDown(self) -> None:
        self.store.close()
        self.temp.cleanup()

    def test_activation_persists_metadata_and_keyring_refresh_only(self) -> None:
        session = self.runtime.activate_inventory(
            "Seed Clinic",
            "seed-clinic",
            self.hardware_id,
            "provider-activation-code-at-least-20",
            "correct-horse-battery-staple",
            "correct-horse-battery-staple",
        )

        stored = self.store.load()
        assert stored is not None
        self.assertEqual(stored.license_id, self.client.license_id)
        self.assertEqual(stored.hardware_id, self.hardware_id)
        self.assertEqual(stored.client_installation_id, self.installation_id)
        self.assertEqual(session.client_installation_id, str(self.installation_id))
        self.assertEqual(self.client.inventory_activation_requests[-1].asset_serial, self.hardware_id)
        self.assertEqual(session.hardware_asset_id, str(self.client.hardware_asset_id))
        self.assertEqual(
            self.store.refresh_token(),
            "refresh-token-0-value-at-least-20",
        )

    def test_replacement_computer_uses_new_installation_for_same_license_and_hardware(self) -> None:
        replacement_credentials = MemoryCredentials()
        replacement_store = ClientAccessStore(
            Path(self.temp.name) / "replacement.sqlite3",
            replacement_credentials,
        )
        replacement_installation = uuid4()
        try:
            replacement = ClientAccessRuntime(
                self.client,
                replacement_store,
                FixedHardware(),
                license_verifier=self.client.verifier,
                client_installation_id=replacement_installation,
                now=lambda: self.now,
                monotonic_ns=lambda: 200,
            ).login("seed-clinic", "correct-horse-battery-staple")
        finally:
            replacement_store.close()

        self.assertEqual(replacement.license_id, str(self.client.license_id))
        self.assertEqual(replacement.hardware_id, self.hardware_id)
        self.assertEqual(replacement.client_installation_id, str(replacement_installation))
        self.assertEqual(
            self.client.login_requests[-1].client_installation_id,
            replacement_installation,
        )

    def test_expiring_access_token_rotates_refresh_once(self) -> None:
        self.client.short_access = True
        self.runtime.login("seed-clinic", "correct-horse-battery-staple")

        token = self.runtime.current_access_token()

        self.assertEqual(len(self.client.refresh_requests), 1)
        self.assertEqual(token, "access-token-1-value-at-least-20")
        self.assertEqual(
            self.store.refresh_token(),
            "refresh-token-1-value-at-least-20",
        )

    def test_concurrent_token_consumers_serialize_one_refresh_rotation(self) -> None:
        self.client.short_access = True
        self.runtime.login("seed-clinic", "correct-horse-battery-staple")
        barrier = threading.Barrier(5)
        tokens: list[str] = []

        def consume() -> None:
            barrier.wait()
            tokens.append(self.runtime.current_access_token())

        workers = [threading.Thread(target=consume) for _ in range(5)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=2)

        self.assertEqual(len(self.client.refresh_requests), 1)
        self.assertEqual(tokens, ["access-token-1-value-at-least-20"] * 5)

    def test_invalid_refresh_clears_credentials_but_preserves_access_metadata(self) -> None:
        self.runtime.login("seed-clinic", "correct-horse-battery-staple")
        self.client.refresh_rejected = True

        with self.assertRaises(AccessAuthenticationFailed):
            self.runtime.refresh()

        self.assertIsNone(self.store.refresh_token())
        self.assertIsNotNone(self.store.load())

    def test_inventory_asset_mismatch_stops_authenticated_handoff(self) -> None:
        self.client.hardware_id = "FFP-DP4864-000002"

        with self.assertRaises(LicenseHardwareMismatch):
            self.runtime.activate_inventory(
                "Seed Clinic",
                "seed-clinic",
                "FFP-DP4864-000001",
                "provider-activation-code-at-least-20",
                "correct-horse-battery-staple",
                "correct-horse-battery-staple",
            )

    def test_settings_require_https_and_explicit_7443_integration_ca(self) -> None:
        ca_path = Path(self.temp.name) / "integration-ca.pem"
        ca_path.write_text("test ca", encoding="utf-8")
        public_key_path = Path(self.temp.name) / "license-public-key"
        public_key_path.write_bytes(
            self.client.private_key.public_key().public_bytes(
                Encoding.Raw,
                PublicFormat.Raw,
            )
        )
        settings = AccessRuntimeSettings.from_environment(
            {
                "FEETFORCEPLATE_API_BASE_URL": "https://127.0.0.1:7443",
                "FEETFORCEPLATE_INTEGRATION_MODE": "1",
                "FEETFORCEPLATE_CA_BUNDLE": str(ca_path),
                "FEETFORCEPLATE_LICENSE_PUBLIC_KEY_FILE": str(public_key_path),
            }
        )
        assert settings is not None
        self.assertTrue(settings.integration_mode)
        self.assertEqual(settings.environment_label, "联调环境")
        self.assertEqual(settings.verify, str(ca_path))
        self.assertEqual(settings.license_key_id, "license/1")
        with self.assertRaises(ValueError):
            AccessRuntimeSettings.from_environment(
                {
                    "FEETFORCEPLATE_API_BASE_URL": "http://127.0.0.1:7443",
                    "FEETFORCEPLATE_LICENSE_PUBLIC_KEY_FILE": str(public_key_path),
                }
            )
        with self.assertRaises(ValueError):
            AccessRuntimeSettings.from_environment(
                {
                    "FEETFORCEPLATE_API_BASE_URL": "https://127.0.0.1:7443",
                    "FEETFORCEPLATE_LICENSE_PUBLIC_KEY_FILE": str(public_key_path),
                }
            )

    def test_packaged_public_cloud_defaults_create_runtime_settings_without_environment(
        self,
    ) -> None:
        resources = Path(self.temp.name) / "packaged-resources"
        resources.mkdir()
        (resources / "cloud-default.json").write_text(
            json.dumps(
                {
                    "schema_version": "feetforceplate-client-cloud-default/1",
                    "channel": "integration",
                    "api_base_url": "https://39.105.216.113:7443",
                    "license_key_id": "license/2-key-1",
                    "ca_bundle_resource": "cloud-ca.pem",
                    "license_public_key_resource": "license-public.key",
                }
            ),
            encoding="utf-8",
        )
        (resources / "cloud-ca.pem").write_text("public test CA", encoding="utf-8")
        (resources / "license-public.key").write_bytes(b"p" * 32)

        settings = AccessRuntimeSettings.from_environment(
            {}, packaged_resource_root=resources
        )

        self.assertIsNotNone(settings)
        assert settings is not None
        self.assertEqual(settings.base_url, "https://39.105.216.113:7443")
        self.assertTrue(settings.integration_mode)
        self.assertEqual(settings.verify, str(resources / "cloud-ca.pem"))
        self.assertEqual(settings.license_key_id, "license/2-key-1")
        self.assertEqual(
            settings.license_public_key_file, resources / "license-public.key"
        )


if __name__ == "__main__":
    unittest.main()
