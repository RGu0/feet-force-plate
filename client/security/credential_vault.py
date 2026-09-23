"""Production bridge from Foundation's CredentialVault port to OS storage.

The application owns this target-system adapter; all callers use the
``techflex_cloud_foundation.CredentialVault`` port.  In particular, a missing
or unsuitable keyring backend is an availability failure, never a reason to
write a fallback file or database value.
"""

from __future__ import annotations

import sys
import os
import stat
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Callable

from platformdirs import user_data_path
from techflex_cloud_foundation import CredentialVault


class CredentialVaultUnavailable(RuntimeError):
    """The required native credential service cannot safely be used."""


_initialization_thread_lock = threading.Lock()


@contextmanager
def _credential_initialization_lock():
    """Serialize first-use reads and writes across processes without storing secrets."""

    path = Path(user_data_path("FeetForcePlate", "TechFlex", ensure_exists=True))
    path = path / ".credential-initialization.lock"
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        raise CredentialVaultUnavailable("credential initialization lock is unavailable") from exc
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise CredentialVaultUnavailable("credential initialization lock is invalid")
        if os.name != "nt":
            if info.st_uid != os.getuid():
                raise CredentialVaultUnavailable("credential initialization lock is invalid")
            os.fchmod(descriptor, 0o600)
            import fcntl

            fcntl.flock(descriptor, fcntl.LOCK_EX)
            unlock = lambda: fcntl.flock(descriptor, fcntl.LOCK_UN)
        else:
            import msvcrt

            if info.st_size == 0:
                os.write(descriptor, b"\0")
            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_LOCK, 1)
            unlock = lambda: msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        try:
            yield
        finally:
            unlock()
    except OSError as exc:
        raise CredentialVaultUnavailable("credential initialization lock is unavailable") from exc
    finally:
        os.close(descriptor)


def get_or_create_credential(
    vault: CredentialVault, key: str, create: Callable[[], str]
) -> str:
    """Return one stable first-use value shared by all cooperating clients."""

    with _initialization_thread_lock, _credential_initialization_lock():
        saved = vault.get(key)
        if saved is not None:
            return saved
        value = create()
        vault.set(key, value)
        if vault.get(key) != value:
            raise CredentialVaultUnavailable("credential initialization was not retained")
        return value


class _KeyringCredentialVault:
    """Adapt a verified keyring backend to Foundation's public port."""

    def __init__(self, backend: object) -> None:
        self._backend = backend

    def get(self, key: str) -> str | None:
        return self._backend.get_password("FeetForcePlate", key)

    def set(self, key: str, value: str) -> None:
        self._backend.set_password("FeetForcePlate", key, value)

    def delete(self, key: str) -> None:
        try:
            self._backend.delete_password("FeetForcePlate", key)
        except Exception as exc:
            if not _is_missing_credential(exc):
                raise


class SystemCredentialVault:
    """Foundation CredentialVault backed only by Keychain or Windows Vault.

    ``backend_loader`` is a narrow test seam.  Production callers omit it, so
    backend selection is verified against the target operating system before
    any secret is read or written.
    """

    def __init__(
        self,
        *,
        platform_name: str | None = None,
        backend_loader: Callable[[str], CredentialVault] | None = None,
    ) -> None:
        platform = platform_name or sys.platform
        if platform not in {"darwin", "win32"}:
            raise CredentialVaultUnavailable("unsupported platform credential vault")
        loader = backend_loader or _load_native_credential_vault
        try:
            self._vault = loader(platform)
        except CredentialVaultUnavailable:
            raise
        except Exception as exc:
            raise CredentialVaultUnavailable(
                "platform credential vault is unavailable"
            ) from exc

    def get(self, key: str) -> str | None:
        return self._call("get", key)

    def set(self, key: str, value: str) -> None:
        self._call("set", key, value)

    def delete(self, key: str) -> None:
        self._call("delete", key)

    def _call(self, method: str, *args: str) -> str | None:
        for attempt in range(2 if method == "set" else 1):
            try:
                return getattr(self._vault, method)(*args)
            except Exception as exc:
                if attempt == 0 and _is_keychain_duplicate_item(exc):
                    continue
                raise CredentialVaultUnavailable(
                    "platform credential vault is unavailable"
                ) from exc
        raise AssertionError("duplicate-item retry must either return or raise")


def _load_native_credential_vault(platform: str) -> CredentialVault:
    try:
        import keyring
    except ImportError as exc:  # pragma: no cover - packaging contract
        raise CredentialVaultUnavailable("platform credential vault is unavailable") from exc
    backend = keyring.get_keyring()
    module_name = type(backend).__module__
    required_module = {
        "darwin": "keyring.backends.macOS",
        "win32": "keyring.backends.Windows",
    }[platform]
    if module_name != required_module or (
        platform == "win32" and type(backend).__name__ != "WinVaultKeyring"
    ):
        raise CredentialVaultUnavailable("platform credential vault is unavailable")
    return _KeyringCredentialVault(backend)


def _is_missing_credential(error: Exception) -> bool:
    try:
        from keyring.errors import PasswordDeleteError
    except ImportError:
        return False
    return isinstance(error, PasswordDeleteError)


def _is_keychain_duplicate_item(error: Exception) -> bool:
    """Recognize only macOS's documented duplicate-generic-password status."""

    return "-25299" in str(error) or "errSecDuplicateItem" in str(error)


__all__ = ["CredentialVaultUnavailable", "SystemCredentialVault", "get_or_create_credential"]
