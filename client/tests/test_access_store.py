from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from client.cloud.access_store import ClientAccessStore
from shared.contracts.access_control import ActivateAccountResponse


class MemoryCredentials:
    def __init__(self) -> None:
        self.values: dict[UUID, str] = {}

    def set_refresh_token(self, account_id: UUID, refresh_token: str) -> None:
        self.values[account_id] = refresh_token

    def get_refresh_token(self, account_id: UUID) -> str | None:
        return self.values.get(account_id)

    def delete_refresh_token(self, account_id: UUID) -> None:
        self.values.pop(account_id, None)


class ClientAccessStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "access.sqlite3"
        self.credentials = MemoryCredentials()
        self.store = ClientAccessStore(self.path, self.credentials)
        self.now = datetime.now(UTC)
        self.account_id = uuid4()
        self.refresh_token = "refresh-secret-value-never-in-sqlite"
        self.access_token = "access-secret-value-never-in-sqlite"

    def tearDown(self) -> None:
        self.store.close()
        self.temp.cleanup()

    def session(self) -> ActivateAccountResponse:
        tenant_id = uuid4()
        license_id = uuid4()
        installation_id = uuid4()
        hardware_id = "usb-serial-0123456789abcdef0123"
        return ActivateAccountResponse.model_validate(
            {
                "tenant_id": tenant_id,
                "account_id": self.account_id,
                "license_id": license_id,
                "hardware_id": hardware_id,
                "client_installation_id": installation_id,
                "access_token": self.access_token,
                "access_token_expires_at": self.now + timedelta(minutes=15),
                "refresh_token": self.refresh_token,
                "refresh_idle_expires_at": self.now + timedelta(days=30),
                "refresh_absolute_expires_at": self.now + timedelta(days=180),
                "signed_license": {
                    "document": {
                        "tenant_id": tenant_id,
                        "account_id": self.account_id,
                        "license_id": license_id,
                        "hardware_id": hardware_id,
                        "status": "ACTIVE",
                        "issued_at": self.now,
                        "valid_from": self.now,
                        "valid_until": self.now + timedelta(days=365),
                        "version": 3,
                        "enabled_features": [
                            "reports.view",
                            "screening.start",
                            "sync.upload",
                        ],
                    },
                    "key_id": "license/2-key-1",
                    "signature": "A" * 86,
                },
                "capabilities": {
                    "allow_new_test": True,
                    "allow_upload": True,
                    "allow_report_view": True,
                },
                "account_state": "ACTIVE",
            }
        )

    def test_persists_metadata_and_keyring_secret_without_sqlite_leak(self) -> None:
        session = self.session()
        state = self.store.save_session(
            session,
            trusted_server_utc=self.now,
            observed_wall_utc=self.now,
            observed_monotonic_ns=5_000_000_000,
        )
        self.store.set_lock_timeout(15)
        state = self.store.load()

        assert state is not None
        self.assertEqual(state.tenant_id, session.tenant_id)
        self.assertEqual(state.account_id, session.account_id)
        self.assertEqual(state.license_id, session.license_id)
        self.assertEqual(state.hardware_id, session.hardware_id)
        self.assertEqual(state.client_installation_id, session.client_installation_id)
        self.assertEqual(state.license_version, 3)
        self.assertEqual(state.lock_timeout_minutes, 15)
        self.assertEqual(self.store.refresh_token(), self.refresh_token)
        self.store._connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        database_bytes = self.path.read_bytes()
        for secret in (
            self.refresh_token,
            self.access_token,
            "correct-horse-battery-staple",
            "activation-code-secret",
        ):
            self.assertNotIn(secret.encode(), database_bytes)

    def test_clock_rollback_and_monotonic_restart_are_untrusted(self) -> None:
        self.store.save_session(
            self.session(),
            trusted_server_utc=self.now,
            observed_wall_utc=self.now,
            observed_monotonic_ns=10_000_000_000,
        )
        self.assertTrue(
            self.store.clock_is_trusted(
                observed_wall_utc=self.now + timedelta(minutes=1),
                observed_monotonic_ns=70_000_000_000,
            )
        )
        self.assertFalse(
            self.store.clock_is_trusted(
                observed_wall_utc=self.now - timedelta(minutes=6),
                observed_monotonic_ns=11_000_000_000,
            )
        )
        self.assertFalse(
            self.store.clock_is_trusted(
                observed_wall_utc=self.now + timedelta(minutes=1),
                observed_monotonic_ns=1,
            )
        )

    def test_clear_credentials_preserves_non_secret_state(self) -> None:
        session = self.session()
        self.store.save_session(
            session,
            trusted_server_utc=self.now,
            observed_wall_utc=self.now,
            observed_monotonic_ns=1,
        )

        self.store.clear_credentials()

        self.assertIsNone(self.store.refresh_token())
        self.assertIsNotNone(self.store.load())


if __name__ == "__main__":
    unittest.main()
