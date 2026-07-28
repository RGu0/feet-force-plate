"""Dual-recipient envelopes for short-lived per-artifact data encryption keys.

This module intentionally models only public-key wrapping and authenticated data
encryption. Production terminal private-key operations belong behind an OS
secure-storage adapter and must not be represented by PEM files.
"""

from __future__ import annotations

from dataclasses import dataclass
import base64
from datetime import UTC, datetime
import hashlib
import json
import os
from typing import Protocol

from cryptography.exceptions import InvalidSignature, InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


_ENVELOPE_VERSION = "dual-envelope/1"
_WRAP_INFO = b"feetforceplate/dek-wrap/p256/v1"


@dataclass(frozen=True, slots=True)
class ServerKeyset:
    """A server-signed public wrapping key selected after License validation."""

    key_id: str
    public_key_pem: bytes


@dataclass(frozen=True, slots=True)
class SignedServerKeyset:
    """A License-bound server wrapping keyset signed by the configuration authority."""

    keyset: ServerKeyset
    tenant_id: str
    terminal_id: str
    expires_at: datetime
    signature: bytes


@dataclass(frozen=True, slots=True)
class TestKeyPair:
    """PEM test fixture only; production private keys stay in the OS keystore."""

    public_key_pem: bytes
    private_key_pem: bytes


class PasswordKeyring(Protocol):
    """The narrow API used by the OS-backed keyring package."""

    def get_password(self, service_name: str, username: str) -> str | None: ...

    def set_password(self, service_name: str, username: str, password: str) -> None: ...


class TerminalKeyHandle(Protocol):
    @property
    def public_key_pem(self) -> bytes: ...

    @property
    def key_id(self) -> str: ...

    def unwrap_dek(self, wrapped: "WrappedDataKey", *, context: str) -> bytes: ...


@dataclass(frozen=True, slots=True)
class WrappedDataKey:
    ephemeral_public_key_der: bytes
    nonce: bytes
    ciphertext: bytes


@dataclass(frozen=True, slots=True)
class DualRecoveryArtifact:
    version: str
    context: str
    nonce: bytes
    ciphertext: bytes
    server_key_id: str
    server_wrapped_dek: WrappedDataKey
    terminal_key_id: str
    terminal_wrapped_dek: WrappedDataKey


class DualEnvelopeBlobCodec:
    """Serialize dual-recipient envelopes into SQLite-safe opaque bytes."""

    _MAGIC = b"FFPDEK2\x00"

    def __init__(self, *, server_keyset: ServerKeyset, terminal_key: TerminalKeyHandle) -> None:
        self._server_keyset = server_keyset
        self._terminal_key = terminal_key

    def encrypt(self, plaintext: bytes, *, context: str) -> bytes:
        artifact = encrypt_for_dual_recovery(
            plaintext,
            context=context,
            server_keyset=self._server_keyset,
            terminal_key_id=self._terminal_key.key_id,
            terminal_public_key_pem=self._terminal_key.public_key_pem,
        )
        return self._MAGIC + json.dumps(
            {
                "version": artifact.version,
                "context": artifact.context,
                "nonce": _encode(artifact.nonce),
                "ciphertext": _encode(artifact.ciphertext),
                "server_key_id": artifact.server_key_id,
                "server_wrapped_dek": _wrapped_to_json(artifact.server_wrapped_dek),
                "terminal_key_id": artifact.terminal_key_id,
                "terminal_wrapped_dek": _wrapped_to_json(artifact.terminal_wrapped_dek),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    def decrypt(self, envelope: bytes, *, context: str) -> bytes:
        if not envelope.startswith(self._MAGIC):
            raise ValueError("unsupported dual-envelope blob")
        try:
            value = json.loads(envelope[len(self._MAGIC) :].decode("utf-8"))
            artifact = DualRecoveryArtifact(
                version=value["version"],
                context=value["context"],
                nonce=_decode(value["nonce"]),
                ciphertext=_decode(value["ciphertext"]),
                server_key_id=value["server_key_id"],
                server_wrapped_dek=_wrapped_from_json(value["server_wrapped_dek"]),
                terminal_key_id=value["terminal_key_id"],
                terminal_wrapped_dek=_wrapped_from_json(value["terminal_wrapped_dek"]),
            )
        except (KeyError, TypeError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise ValueError("malformed dual-envelope blob") from exc
        if artifact.context != context:
            raise ValueError("dual-envelope context mismatch")
        return decrypt_for_terminal_handle(artifact, self._terminal_key)


class KeyringTerminalKeyHandle:
    """A terminal P-256 private key stored in the platform credential vault.

    The optional backend exists only to make the storage contract testable. At
    runtime the ``keyring`` package delegates to macOS Keychain or the Windows
    credential vault. A native Secure Enclave/CNG adapter can later implement
    the same public-key and unwrap surface without exporting private material.
    """

    def __init__(
        self,
        *,
        service_name: str,
        account_name: str,
        keyring_backend: PasswordKeyring | None = None,
    ) -> None:
        self._service_name = service_name
        self._account_name = account_name
        self._backend = keyring_backend or _runtime_keyring()
        self._private_key_pem: bytes | None = None

    @property
    def public_key_pem(self) -> bytes:
        return self._private_key().public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )

    @property
    def key_id(self) -> str:
        return "terminal-p256-" + hashlib.sha256(self.public_key_pem).hexdigest()[:16]

    def unwrap_dek(self, wrapped: WrappedDataKey, *, context: str) -> bytes:
        return _unwrap_dek(
            wrapped,
            self._private_key().private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ),
            context.encode("utf-8"),
        )

    def _private_key(self) -> ec.EllipticCurvePrivateKey:
        if self._private_key_pem is None:
            saved = self._backend.get_password(self._service_name, self._account_name)
            if saved is None:
                generated = ec.generate_private_key(ec.SECP256R1())
                pem = generated.private_bytes(
                    serialization.Encoding.PEM,
                    serialization.PrivateFormat.PKCS8,
                    serialization.NoEncryption(),
                )
                self._backend.set_password(
                    self._service_name,
                    self._account_name,
                    base64.b64encode(pem).decode("ascii"),
                )
                self._private_key_pem = pem
            else:
                self._private_key_pem = base64.b64decode(saved.encode("ascii"), validate=True)
        loaded = serialization.load_pem_private_key(self._private_key_pem, password=None)
        if not isinstance(loaded, ec.EllipticCurvePrivateKey) or not isinstance(
            loaded.curve, ec.SECP256R1
        ):
            raise ValueError("terminal key must be P-256")
        return loaded


def generate_test_keypair() -> TestKeyPair:
    """Generate an exportable P-256 pair for tests and development injection only."""

    private_key = ec.generate_private_key(ec.SECP256R1())
    return TestKeyPair(
        public_key_pem=private_key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ),
        private_key_pem=private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
    )


def sign_server_keyset_for_test(
    keyset: ServerKeyset,
    *,
    tenant_id: str,
    terminal_id: str,
    expires_at: datetime,
    authority_private_key_pem: bytes,
) -> SignedServerKeyset:
    """Test-only stand-in for the server-side License/keyset issuer."""

    private_key = serialization.load_pem_private_key(authority_private_key_pem, password=None)
    if not isinstance(private_key, ec.EllipticCurvePrivateKey) or not isinstance(
        private_key.curve, ec.SECP256R1
    ):
        raise ValueError("authority private key must be P-256")
    unsigned = SignedServerKeyset(keyset, tenant_id, terminal_id, expires_at, b"")
    return SignedServerKeyset(
        keyset,
        tenant_id,
        terminal_id,
        expires_at,
        private_key.sign(_keyset_payload(unsigned), ec.ECDSA(hashes.SHA256())),
    )


def verify_server_keyset(
    signed: SignedServerKeyset,
    *,
    authority_public_key_pem: bytes,
    expected_tenant_id: str,
    expected_terminal_id: str,
    now: datetime,
) -> ServerKeyset:
    """Accept only a signed, unexpired keyset bound to this registered terminal."""

    public_key = serialization.load_pem_public_key(authority_public_key_pem)
    if not isinstance(public_key, ec.EllipticCurvePublicKey) or not isinstance(
        public_key.curve, ec.SECP256R1
    ):
        raise ValueError("authority public key must be P-256")
    try:
        public_key.verify(signed.signature, _keyset_payload(signed), ec.ECDSA(hashes.SHA256()))
    except InvalidSignature as exc:
        raise ValueError("server keyset signature is invalid") from exc
    if signed.tenant_id != expected_tenant_id or signed.terminal_id != expected_terminal_id:
        raise ValueError("server keyset is not bound to this License terminal")
    if signed.expires_at.tzinfo is None or now.tzinfo is None:
        raise ValueError("server keyset timestamps must include a timezone")
    if signed.expires_at <= now.astimezone(UTC):
        raise ValueError("server keyset has expired")
    return signed.keyset


def encrypt_for_dual_recovery(
    plaintext: bytes,
    *,
    context: str,
    server_keyset: ServerKeyset,
    terminal_key_id: str,
    terminal_public_key_pem: bytes,
) -> DualRecoveryArtifact:
    """Encrypt a payload with a random DEK and wrap it for both recipients."""

    if not plaintext:
        raise ValueError("payload must not be empty")
    if not context or not server_keyset.key_id or not terminal_key_id:
        raise ValueError("context and recipient key IDs are required")
    dek = os.urandom(32)
    aad = context.encode("utf-8")
    nonce = os.urandom(12)
    return DualRecoveryArtifact(
        version=_ENVELOPE_VERSION,
        context=context,
        nonce=nonce,
        ciphertext=AESGCM(dek).encrypt(nonce, plaintext, aad),
        server_key_id=server_keyset.key_id,
        server_wrapped_dek=_wrap_dek(dek, server_keyset.public_key_pem, aad),
        terminal_key_id=terminal_key_id,
        terminal_wrapped_dek=_wrap_dek(dek, terminal_public_key_pem, aad),
    )


def decrypt_for_server(artifact: DualRecoveryArtifact, private_key_pem: bytes) -> bytes:
    return _decrypt(artifact, artifact.server_wrapped_dek, private_key_pem)


def decrypt_for_terminal(artifact: DualRecoveryArtifact, private_key_pem: bytes) -> bytes:
    return _decrypt(artifact, artifact.terminal_wrapped_dek, private_key_pem)


def decrypt_for_terminal_handle(
    artifact: DualRecoveryArtifact, terminal_key: TerminalKeyHandle
) -> bytes:
    try:
        dek = terminal_key.unwrap_dek(artifact.terminal_wrapped_dek, context=artifact.context)
        return AESGCM(dek).decrypt(
            artifact.nonce, artifact.ciphertext, artifact.context.encode("utf-8")
        )
    except (InvalidTag, TypeError, ValueError) as exc:
        raise ValueError("cannot decrypt dual-recovery artifact") from exc


def _decrypt(
    artifact: DualRecoveryArtifact,
    wrapped_dek: WrappedDataKey,
    private_key_pem: bytes,
) -> bytes:
    if artifact.version != _ENVELOPE_VERSION:
        raise ValueError("unsupported envelope version")
    try:
        dek = _unwrap_dek(wrapped_dek, private_key_pem, artifact.context.encode("utf-8"))
        return AESGCM(dek).decrypt(
            artifact.nonce, artifact.ciphertext, artifact.context.encode("utf-8")
        )
    except (InvalidTag, TypeError, ValueError) as exc:
        raise ValueError("cannot decrypt dual-recovery artifact") from exc


def _wrap_dek(dek: bytes, recipient_public_key_pem: bytes, aad: bytes) -> WrappedDataKey:
    recipient = serialization.load_pem_public_key(recipient_public_key_pem)
    if not isinstance(recipient, ec.EllipticCurvePublicKey) or not isinstance(
        recipient.curve, ec.SECP256R1
    ):
        raise ValueError("recipient key must be P-256")
    ephemeral = ec.generate_private_key(ec.SECP256R1())
    wrapping_key = _derive_wrapping_key(ephemeral.exchange(ec.ECDH(), recipient), aad)
    nonce = os.urandom(12)
    return WrappedDataKey(
        ephemeral_public_key_der=ephemeral.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ),
        nonce=nonce,
        ciphertext=AESGCM(wrapping_key).encrypt(nonce, dek, aad),
    )


def _unwrap_dek(wrapped: WrappedDataKey, private_key_pem: bytes, aad: bytes) -> bytes:
    private_key = serialization.load_pem_private_key(private_key_pem, password=None)
    ephemeral = serialization.load_der_public_key(wrapped.ephemeral_public_key_der)
    if not isinstance(private_key, ec.EllipticCurvePrivateKey) or not isinstance(
        private_key.curve, ec.SECP256R1
    ):
        raise ValueError("recipient private key must be P-256")
    if not isinstance(ephemeral, ec.EllipticCurvePublicKey) or not isinstance(
        ephemeral.curve, ec.SECP256R1
    ):
        raise ValueError("ephemeral key must be P-256")
    return AESGCM(_derive_wrapping_key(private_key.exchange(ec.ECDH(), ephemeral), aad)).decrypt(
        wrapped.nonce, wrapped.ciphertext, aad
    )


def _derive_wrapping_key(shared_secret: bytes, aad: bytes) -> bytes:
    return HKDF(
        algorithm=hashes.SHA256(), length=32, salt=None, info=_WRAP_INFO + aad
    ).derive(shared_secret)


def _runtime_keyring() -> PasswordKeyring:
    try:
        import keyring
    except ImportError as exc:  # pragma: no cover - packaging is verified separately
        raise RuntimeError("system credential storage package is unavailable") from exc
    return keyring


def _keyset_payload(value: SignedServerKeyset) -> bytes:
    if value.expires_at.tzinfo is None:
        raise ValueError("server keyset expiry must include a timezone")
    return json.dumps(
        {
            "key_id": value.keyset.key_id,
            "public_key_pem": _encode(value.keyset.public_key_pem),
            "tenant_id": value.tenant_id,
            "terminal_id": value.terminal_id,
            "expires_at": value.expires_at.astimezone(UTC).isoformat(),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _encode(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _decode(value: str) -> bytes:
    return base64.b64decode(value.encode("ascii"), validate=True)


def _wrapped_to_json(value: WrappedDataKey) -> dict[str, str]:
    return {
        "ephemeral_public_key_der": _encode(value.ephemeral_public_key_der),
        "nonce": _encode(value.nonce),
        "ciphertext": _encode(value.ciphertext),
    }


def _wrapped_from_json(value: object) -> WrappedDataKey:
    if not isinstance(value, dict):
        raise ValueError("wrapped DEK must be an object")
    return WrappedDataKey(
        ephemeral_public_key_der=_decode(value["ephemeral_public_key_der"]),
        nonce=_decode(value["nonce"]),
        ciphertext=_decode(value["ciphertext"]),
    )
