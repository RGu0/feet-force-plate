from __future__ import annotations

import sys
from types import SimpleNamespace
from uuid import uuid4

import pytest
from keyring.errors import PasswordDeleteError

import client.app.windows_credential_integrity as windows_credential_integrity
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


class _MissingCredentialBackend:
    def delete_password(self, service_name: str, username: str) -> None:
        raise PasswordDeleteError("credential not found")


class _MisleadingDeleteFailureBackend:
    def delete_password(self, service_name: str, username: str) -> None:
        raise OSError("backend unavailable; target not found")


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


def test_indeterminate_elevation_probe_is_rejected_without_native_detail() -> None:
    def failed_probe() -> bool:
        raise OSError("native-token-query-failed")

    with pytest.raises(RuntimeError) as raised:
        require_standard_user_process(is_elevated=failed_probe)

    assert str(raised.value) == "unable to verify Windows process integrity"


def test_native_elevation_probe_failure_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(windows_credential_integrity.os, "name", "nt")
    reported_error = [0]

    def failed_probe_library(*_args, **_kwargs):
        reported_error[0] = 5
        return SimpleNamespace(IsUserAnAdmin=lambda: False)

    monkeypatch.setattr(
        windows_credential_integrity.ctypes, "WinDLL", failed_probe_library
    )
    monkeypatch.setattr(
        windows_credential_integrity.ctypes,
        "windll",
        SimpleNamespace(shell32=SimpleNamespace(IsUserAnAdmin=lambda: False)),
    )
    monkeypatch.setattr(
        windows_credential_integrity.ctypes, "get_last_error", lambda: reported_error[0]
    )

    with pytest.raises(RuntimeError) as raised:
        require_standard_user_process()

    assert str(raised.value) == "unable to verify Windows process integrity"


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


def test_missing_credential_delete_is_idempotent() -> None:
    store = KeyringCredentialStore(backend=_MissingCredentialBackend())

    store.delete_refresh_token(uuid4())


def test_credential_manager_delete_failure_with_misleading_not_found_text_is_rejected() -> None:
    store = KeyringCredentialStore(backend=_MisleadingDeleteFailureBackend())

    with pytest.raises(RuntimeError) as raised:
        store.delete_refresh_token(uuid4())

    assert str(raised.value) == "system credential storage is unavailable"


def test_missing_keyring_module_is_reported_without_import_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "keyring", None)

    with pytest.raises(RuntimeError) as raised:
        KeyringCredentialStore()

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