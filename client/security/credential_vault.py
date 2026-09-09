"""Production bridge from Foundation's CredentialVault port to OS storage.

The application owns this target-system adapter; all callers use the
``techflex_cloud_foundation.CredentialVault`` port.  In particular, a missing
or unsuitable keyring backend is an availability failure, never a reason to
write a fallback file or database value.
"""

from __future__ import annotations

import sys
from typing import Callable

from techflex_cloud_foundation import CredentialVault


class CredentialVaultUnavailable(RuntimeError):
    """The required native credential service cannot safely be used."""


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
            if "not found" not in str(exc).lower():
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
        try:
            return getattr(self._vault, method)(*args)
        except Exception as exc:
            raise CredentialVaultUnavailable(
                "platform credential vault is unavailable"
            ) from exc


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
    if module_name != required_module:
        raise CredentialVaultUnavailable("platform credential vault is unavailable")
    return _KeyringCredentialVault(backend)


__all__ = ["CredentialVaultUnavailable", "SystemCredentialVault"]
