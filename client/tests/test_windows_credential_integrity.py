from __future__ import annotations

import sys
from types import SimpleNamespace
from uuid import uuid4

import pytest

import client.cloud.access_store as access_store
from client.cloud.access_store import KeyringCredentialStore
from client.app.windows_credential_integrity import require_standard_user_process


class _UnavailableCredentialBackend:
    def get_password(self, service_name: str, username: str) -> str | None:
        raise OSError("refresh-token-must-never-reach-the-operator")


class _WriteUnavailableCredentialBackend:
    def set_password(self, service_name: str, username: str, password: str) -> None:
        raise OSError("refresh-token-must-never-reach-the-operator")


class _DeleteUnavailableCredentialBackend:
    def delete_password(self, service_name: str, username: str) -> None:
        raise OSError("refresh-token-must-never-reach-the-operator")


class _NotWindowsCredentialManager:
    def get_keyring(self) -> object:
        return object()


WinVaultKeyring = type("WinVaultKeyring", (), {"__module__": "keyring.backends.Windows"})


class _WindowsCredentialManager:
    def get_keyring(self) -> object:
        return WinVaultKeyring()


def test_elevated_process_is_rejected_before_it_can_create_user_vault_data() -> None:
    with pytest.raises(RuntimeError, match="must not run as administrator"):
        require_standard_user_process(is_elevated=lambda: True)


def test_standard_user_process_is_allowed() -> None:
    require_standard_user_process(is_elevated=lambda: False)


def test_credential_manager_read_failure_has_no_backend_or_secret_detail() -> None:
    store = KeyringCredentialStore(backend=_UnavailableCredentialBackend())

    with pytest.raises(RuntimeError) as raised:
        store.get_refresh_token(uuid4())

    assert str(raised.value) == "system credential storage is unavailable"


def test_credential_manager_write_failure_has_no_backend_or_secret_detail() -> None:
    store = KeyringCredentialStore(backend=_WriteUnavailableCredentialBackend())

    with pytest.raises(RuntimeError) as raised:
        store.set_refresh_token(uuid4(), "refresh-token-must-never-reach-the-operator")

    assert str(raised.value) == "system credential storage is unavailable"


def test_credential_manager_delete_failure_has_no_backend_or_secret_detail() -> None:
    store = KeyringCredentialStore(backend=_DeleteUnavailableCredentialBackend())

    with pytest.raises(RuntimeError) as raised:
        store.delete_refresh_token(uuid4())

    assert str(raised.value) == "system credential storage is unavailable"


def test_windows_requires_credential_manager_instead_of_another_keyring_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(access_store.os, "name", "nt")
    monkeypatch.setitem(
        sys.modules,
        "keyring",
        SimpleNamespace(get_keyring=_NotWindowsCredentialManager().get_keyring),
    )

    with pytest.raises(RuntimeError, match="Windows Credential Manager backend is required"):
        KeyringCredentialStore()


def test_windows_accepts_the_native_credential_manager_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(access_store.os, "name", "nt")
    monkeypatch.setitem(
        sys.modules,
        "keyring",
        SimpleNamespace(get_keyring=_WindowsCredentialManager().get_keyring),
    )

    KeyringCredentialStore()