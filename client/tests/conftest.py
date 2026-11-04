"""Shared fixtures for client tests."""

from __future__ import annotations

import pytest


class _MemoryCredentialVault:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def set(self, key: str, value: str) -> None:
        self.values[key] = value

    def delete(self, key: str) -> None:
        self.values.pop(key, None)


@pytest.fixture(autouse=True)
def _memory_default_credential_vault(monkeypatch) -> None:
    """Keep store defaults off the OS credential store during tests.

    Stores fall back to ``SystemCredentialVault()``, which supports only the
    macOS Keychain and Windows Credential Manager and would otherwise write
    test secrets into the developer's real store. The adapter itself is
    covered by ``test_credential_vault`` and ``test_windows_credential_integrity``.
    """

    vault = _MemoryCredentialVault()
    for module in (
        "client.app.institution_store",
        "client.app.local_store",
        "client.cloud.access_store",
        "client.security.key_envelope",
    ):
        monkeypatch.setattr(f"{module}.SystemCredentialVault", lambda: vault)
