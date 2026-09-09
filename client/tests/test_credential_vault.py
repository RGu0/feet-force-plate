from __future__ import annotations

import pytest

from client.security.credential_vault import (
    CredentialVaultUnavailable,
    SystemCredentialVault,
)
from client.cloud.access_store import CredentialVaultStore
from uuid import UUID


class _MemoryVault:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def set(self, key: str, value: str) -> None:
        self.values[key] = value

    def delete(self, key: str) -> None:
        self.values.pop(key, None)


class _DuplicateThenUpdateVault(_MemoryVault):
    def __init__(self) -> None:
        super().__init__()
        self._first_set = True

    def set(self, key: str, value: str) -> None:
        if self._first_set:
            self._first_set = False
            raise RuntimeError("Keychain returned errSecDuplicateItem (-25299)")
        super().set(key, value)


def test_system_credential_vault_delegates_namespaced_values_to_foundation_port() -> None:
    """Fails if a client secret bypasses the CredentialVault port."""

    backend = _MemoryVault()
    vault = SystemCredentialVault(
        platform_name="darwin",
        backend_loader=lambda _platform: backend,
    )

    vault.set("FeetForcePlate.access/refresh:account-1", "synthetic-refresh-token")

    assert vault.get("FeetForcePlate.access/refresh:account-1") == "synthetic-refresh-token"
    vault.delete("FeetForcePlate.access/refresh:account-1")
    assert vault.get("FeetForcePlate.access/refresh:account-1") is None


def test_system_credential_vault_rejects_an_unsupported_platform_without_fallback() -> None:
    """Fails if production can silently substitute plaintext storage."""

    with pytest.raises(CredentialVaultUnavailable, match="unsupported platform"):
        SystemCredentialVault(platform_name="linux")


def test_system_credential_vault_recovers_one_keychain_duplicate_item_race() -> None:
    """Fails if a concurrent Keychain add becomes a permanent auth failure."""

    backend = _DuplicateThenUpdateVault()
    vault = SystemCredentialVault(
        platform_name="darwin",
        backend_loader=lambda _platform: backend,
    )

    vault.set("FeetForcePlate.access/refresh:account-1", "synthetic-refresh-token")

    assert backend.get("FeetForcePlate.access/refresh:account-1") == "synthetic-refresh-token"


def test_refresh_tokens_use_the_foundation_credential_vault_not_sqlite_or_keyring() -> None:
    """Fails if refresh-token storage bypasses the Foundation port."""

    backend = _MemoryVault()
    credentials = CredentialVaultStore(backend)
    account_id = UUID("11111111-1111-1111-1111-111111111111")

    credentials.set_refresh_token(account_id, "synthetic-refresh-token")

    assert backend.values == {
        "FeetForcePlate.access/refresh:11111111-1111-1111-1111-111111111111": "synthetic-refresh-token"
    }
