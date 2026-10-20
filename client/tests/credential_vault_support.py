"""Platform gate for tests that reach the production SystemCredentialVault."""

from __future__ import annotations

import sys

import pytest


# SystemCredentialVault deliberately supports only the macOS Keychain and the
# Windows Credential Manager; other platforms raise CredentialVaultUnavailable.
requires_system_credential_vault = pytest.mark.skipif(
    sys.platform not in {"darwin", "win32"},
    reason="the client credential vault supports only macOS Keychain and Windows Credential Manager",
)
