from __future__ import annotations

import sys
from ctypes import wintypes
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


def test_native_token_elevation_open_failure_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Kernel32:
        def GetCurrentProcess(self) -> int:
            return -1

    class FailingAdvapi32:
        def OpenProcessToken(self, *_args) -> bool:
            return False

    monkeypatch.setattr(windows_credential_integrity.os, "name", "nt")

    with pytest.raises(RuntimeError, match="Windows token elevation query failed"):
        windows_credential_integrity._is_windows_process_elevated(
            kernel32=Kernel32(),
            advapi32=FailingAdvapi32(),
        )


def test_native_token_query_configures_pointer_sized_win32_signatures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Function:
        def __init__(self, callback):
            self.callback = callback
            self.argtypes = None
            self.restype = None

        def __call__(self, *args):
            return self.callback(*args)

    kernel32 = SimpleNamespace()
    kernel32.GetCurrentProcess = Function(lambda: -1)

    def open_process_token(_process, _access, handle):
        handle._obj.value = 1
        return True

    kernel32.CloseHandle = Function(lambda _handle: True)
    advapi32 = SimpleNamespace()
    advapi32.OpenProcessToken = Function(open_process_token)

    def get_token_information(_token, _kind, elevation, size, returned):
        elevation._obj.TokenIsElevated = 0
        returned._obj.value = size
        return True

    advapi32.GetTokenInformation = Function(get_token_information)

    def load_library(name: str, *, use_last_error: bool):
        assert use_last_error is True
        return {"kernel32": kernel32, "advapi32": advapi32}[name]

    monkeypatch.setattr(windows_credential_integrity.os, "name", "nt")
    monkeypatch.setattr(windows_credential_integrity.ctypes, "WinDLL", load_library)

    assert windows_credential_integrity._is_windows_process_elevated() is False
    assert kernel32.GetCurrentProcess.restype is wintypes.HANDLE
    assert advapi32.OpenProcessToken.restype is wintypes.BOOL
    assert advapi32.GetTokenInformation.restype is wintypes.BOOL
    assert kernel32.CloseHandle.restype is wintypes.BOOL


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