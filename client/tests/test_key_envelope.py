from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
import pytest

from client.security.key_envelope import (
    DualEnvelopeBlobCodec,
    KeyringTerminalKeyHandle,
    ServerKeyset,
    decrypt_for_terminal_handle,
    decrypt_for_server,
    decrypt_for_terminal,
    encrypt_for_dual_recovery,
    generate_test_keypair,
    sign_server_keyset_for_test,
    verify_server_keyset,
)


class _MemoryKeyring:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, account: str) -> str | None:
        return self.values.get((service, account))

    def set_password(self, service: str, account: str, value: str) -> None:
        self.values[(service, account)] = value


def test_dual_envelope_allows_server_and_terminal_to_recover_one_payload() -> None:
    server = generate_test_keypair()
    terminal = generate_test_keypair()
    keyset = ServerKeyset(key_id="tenant-key-2026-07", public_key_pem=server.public_key_pem)

    artifact = encrypt_for_dual_recovery(
        b"replay debug report payload",
        context="report:replay-1:1",
        server_keyset=keyset,
        terminal_key_id="terminal-42",
        terminal_public_key_pem=terminal.public_key_pem,
    )

    assert artifact.server_key_id == "tenant-key-2026-07"
    assert artifact.terminal_key_id == "terminal-42"
    assert not hasattr(artifact, "dek")
    assert decrypt_for_server(artifact, server.private_key_pem) == b"replay debug report payload"
    assert decrypt_for_terminal(artifact, terminal.private_key_pem) == b"replay debug report payload"


def test_terminal_private_key_cannot_recover_server_only_envelope() -> None:
    server = generate_test_keypair()
    terminal = generate_test_keypair()
    other_terminal = generate_test_keypair()
    artifact = encrypt_for_dual_recovery(
        b"sensitive",
        context="subject:1",
        server_keyset=ServerKeyset("server-v1", server.public_key_pem),
        terminal_key_id="terminal-42",
        terminal_public_key_pem=terminal.public_key_pem,
    )

    with pytest.raises(ValueError, match="cannot decrypt"):
        decrypt_for_terminal(artifact, other_terminal.private_key_pem)


def test_keyring_terminal_handle_persists_only_the_terminal_private_key() -> None:
    keyring = _MemoryKeyring()
    handle = KeyringTerminalKeyHandle(
        service_name="FeetForcePlate.test",
        account_name="terminal-42",
        keyring_backend=keyring,
    )
    server = generate_test_keypair()
    artifact = encrypt_for_dual_recovery(
        b"persistent local record",
        context="record:42",
        server_keyset=ServerKeyset("server-v1", server.public_key_pem),
        terminal_key_id=handle.key_id,
        terminal_public_key_pem=handle.public_key_pem,
    )

    reopened = KeyringTerminalKeyHandle(
        service_name="FeetForcePlate.test",
        account_name="terminal-42",
        keyring_backend=keyring,
    )

    assert reopened.key_id == handle.key_id
    assert decrypt_for_terminal_handle(artifact, reopened) == b"persistent local record"
    assert len(keyring.values) == 1


def test_dual_envelope_blob_codec_keeps_plaintext_out_of_sqlite_value() -> None:
    keyring = _MemoryKeyring()
    terminal = KeyringTerminalKeyHandle(
        service_name="FeetForcePlate.test",
        account_name="terminal-42",
        keyring_backend=keyring,
    )
    server = generate_test_keypair()
    codec = DualEnvelopeBlobCodec(
        server_keyset=ServerKeyset("server-v1", server.public_key_pem),
        terminal_key=terminal,
    )

    stored = codec.encrypt(b"subject external-id: 123456", context="subject:42")

    assert b"123456" not in stored
    reopened = DualEnvelopeBlobCodec(
        server_keyset=ServerKeyset("server-v1", server.public_key_pem),
        terminal_key=KeyringTerminalKeyHandle(
            service_name="FeetForcePlate.test",
            account_name="terminal-42",
            keyring_backend=keyring,
        ),
    )
    assert reopened.decrypt(stored, context="subject:42") == b"subject external-id: 123456"


def test_signed_server_keyset_requires_matching_license_bound_terminal() -> None:
    authority = generate_test_keypair()
    encryption = generate_test_keypair()
    issued_at = datetime(2026, 7, 23, tzinfo=UTC)
    signed = sign_server_keyset_for_test(
        ServerKeyset("tenant-key-1", encryption.public_key_pem),
        tenant_id="tenant-1",
        terminal_id="terminal-1",
        expires_at=issued_at + timedelta(hours=24),
        authority_private_key_pem=authority.private_key_pem,
    )

    verified = verify_server_keyset(
        signed,
        authority_public_key_pem=authority.public_key_pem,
        expected_tenant_id="tenant-1",
        expected_terminal_id="terminal-1",
        now=issued_at,
    )

    assert verified == ServerKeyset("tenant-key-1", encryption.public_key_pem)
    with pytest.raises(ValueError, match="signature"):
        verify_server_keyset(
            replace(signed, terminal_id="terminal-2"),
            authority_public_key_pem=authority.public_key_pem,
            expected_tenant_id="tenant-1",
            expected_terminal_id="terminal-1",
            now=issued_at,
        )
