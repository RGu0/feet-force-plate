"""Encrypted, privacy-safe diagnostic exports for the packaged client."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from io import BytesIO
from pathlib import Path
from typing import Literal
from uuid import UUID
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from pydantic import ConfigDict, Field, ValidationError, field_validator

from shared.contracts.client_sync import canonical_json_bytes
from shared.contracts.cloud import ContractModel
from shared.contracts.validation_telemetry import TechnicalIdentifier

from .safe_events import SafeClientEventStore, SafeClientLogRecord


_ENVELOPE_SCHEMA = "ffpdiag/1"
_ARCHIVE_TIMESTAMP = (2026, 1, 1, 0, 0, 0)
_ARCHIVE_FILENAMES = ("manifest.json", "safe-events.jsonl", "integrity.json")


class PlatformFamily(StrEnum):
    """The small, non-identifying platform taxonomy safe to include in a bundle."""

    MACOS = "macos"
    WINDOWS = "windows"
    LINUX = "linux"


class SafeDiagnosticMetadata(ContractModel):
    """Allowlisted manifest facts; no paths, identity, or free-form text."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["safe-diagnostic/1"] = "safe-diagnostic/1"
    created_at: datetime
    platform_family: PlatformFamily
    client_installation_id: UUID
    app_version: TechnicalIdentifier
    protocol_version: TechnicalIdentifier
    data_mode_version: TechnicalIdentifier
    config_version: TechnicalIdentifier
    event_count: int = Field(ge=0)
    contains_customer_data: Literal[False] = False

    @field_validator("created_at")
    @classmethod
    def require_utc_datetime(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("created_at must use UTC")
        return value.astimezone(UTC)


@dataclass(frozen=True)
class SupportRecipient:
    """The pinned non-secret support public key selected by the packaged build."""

    key_id: str
    public_key: X25519PublicKey

    def __post_init__(self) -> None:
        _validate_recipient_key_id(self.key_id)
        if not isinstance(self.public_key, X25519PublicKey):
            raise ValueError("recipient public key must be an X25519 public key")

    @classmethod
    def from_public_bytes(cls, key_id: str, public_key: bytes) -> SupportRecipient:
        if type(public_key) is not bytes:
            raise ValueError("recipient public key must be valid X25519 bytes")
        try:
            return cls(key_id=key_id, public_key=X25519PublicKey.from_public_bytes(public_key))
        except (TypeError, ValueError) as exc:
            raise ValueError("recipient public key must be valid X25519 bytes") from exc


@dataclass(frozen=True)
class DiagnosticExportResult:
    """The non-sensitive receipt returned after a successful private publication."""

    destination: Path
    recipient_key_id: str
    event_count: int
    ciphertext_sha256: str


class SafeDiagnosticExporter:
    """Export only revalidated safe records in an authenticated encrypted envelope."""

    def __init__(
        self,
        store: SafeClientEventStore,
        recipient: SupportRecipient,
        metadata: SafeDiagnosticMetadata,
    ) -> None:
        self._store = store
        self._recipient = recipient
        self._metadata = metadata

    def export(self, destination: Path) -> DiagnosticExportResult:
        destination = Path(destination)
        _validate_destination(destination)
        records = _revalidate_records(self._store.verified_records())
        if len(records) != self._metadata.event_count:
            raise ValueError("safe diagnostic event count does not match verified records")
        archive = _build_archive(self._metadata, records)
        envelope = _encrypt_archive(archive, self._recipient)
        _publish_private_envelope(destination, envelope)
        return DiagnosticExportResult(
            destination=destination,
            recipient_key_id=self._recipient.key_id,
            event_count=len(records),
            ciphertext_sha256=hashlib.sha256(envelope).hexdigest(),
        )


def decrypt_diagnostic_envelope(payload: bytes, private_key: X25519PrivateKey) -> bytes:
    """Decrypt a test/support-tool envelope and reject altered public metadata."""
    envelope = _parse_canonical_envelope(payload)
    if set(envelope) != {
        "schema",
        "recipient_key_id",
        "ephemeral_public_key",
        "nonce",
        "ciphertext",
        "ciphertext_sha256",
    }:
        raise ValueError("invalid ffpdiag envelope fields")
    if envelope["schema"] != _ENVELOPE_SCHEMA:
        raise ValueError("unsupported ffpdiag envelope schema")
    if not isinstance(private_key, X25519PrivateKey):
        raise ValueError("private key must be an X25519 private key")
    try:
        recipient_key_id = _validate_recipient_key_id(
            _require_string(envelope, "recipient_key_id")
        )
        ephemeral_public_key_text = _require_string(envelope, "ephemeral_public_key")
        nonce_text = _require_string(envelope, "nonce")
        ephemeral_public_key = X25519PublicKey.from_public_bytes(
            _decode_base64(ephemeral_public_key_text)
        )
        nonce = _decode_base64(nonce_text)
        ciphertext = _decode_base64(_require_string(envelope, "ciphertext"))
        ciphertext_sha256 = _require_string(envelope, "ciphertext_sha256")
    except ValueError as exc:
        raise ValueError("invalid ffpdiag envelope values") from exc
    if len(nonce) != 12 or hashlib.sha256(ciphertext).hexdigest() != ciphertext_sha256:
        raise ValueError("invalid ffpdiag envelope integrity")
    content_key = _derive_content_key(private_key.exchange(ephemeral_public_key), recipient_key_id)
    aad = _canonical_header(recipient_key_id, ephemeral_public_key_text, nonce_text)
    try:
        return AESGCM(content_key).decrypt(nonce, ciphertext, aad)
    except Exception as exc:
        raise ValueError("ffpdiag envelope authentication failed") from exc


def _parse_canonical_envelope(payload: bytes) -> dict[str, object]:
    if type(payload) is not bytes:
        raise ValueError("invalid ffpdiag envelope")
    try:
        envelope = json.loads(payload.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError("invalid ffpdiag envelope") from exc
    if not isinstance(envelope, dict):
        raise ValueError("invalid ffpdiag envelope")
    try:
        canonical_envelope = canonical_json_bytes(envelope)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid ffpdiag envelope") from exc
    if payload != canonical_envelope:
        raise ValueError("invalid ffpdiag envelope")
    return envelope


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    envelope: dict[str, object] = {}
    for key, value in pairs:
        if key in envelope:
            raise ValueError("duplicate JSON key")
        envelope[key] = value
    return envelope


def _validate_recipient_key_id(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("recipient key ID must be a string")
    if (
        not value
        or not value.isascii()
        or len(value) > 128
        or not value[0].isalnum()
        or any(not (character.isalnum() or character in "._-") for character in value)
    ):
        raise ValueError("recipient key ID must be a 1-128 character ASCII identifier")
    return value


def _revalidate_records(records: tuple[object, ...]) -> tuple[SafeClientLogRecord, ...]:
    verified: list[SafeClientLogRecord] = []
    previous_sha256: str | None = None
    try:
        for raw_record in records:
            record = SafeClientLogRecord.model_validate(raw_record)
            expected = _record_digest(record)
            if record.previous_sha256 != previous_sha256 or record.sha256 != expected:
                raise ValueError("invalid verified safe event chain")
            verified.append(record)
            previous_sha256 = record.sha256
    except (ValidationError, TypeError, ValueError) as exc:
        raise ValueError("safe diagnostic records failed strict verification") from exc
    return tuple(verified)


def _record_digest(record: SafeClientLogRecord) -> str:
    previous_digest_bytes = bytes.fromhex(record.previous_sha256) if record.previous_sha256 else b""
    return hashlib.sha256(canonical_json_bytes(record.event) + previous_digest_bytes).hexdigest()


def _build_archive(metadata: SafeDiagnosticMetadata, records: tuple[SafeClientLogRecord, ...]) -> bytes:
    manifest = canonical_json_bytes(metadata)
    safe_events = b"".join(canonical_json_bytes(record) + b"\n" for record in records)
    integrity = canonical_json_bytes(
        {
            "schema_version": "safe-diagnostic-integrity/1",
            "entries": {
                "manifest.json": hashlib.sha256(manifest).hexdigest(),
                "safe-events.jsonl": hashlib.sha256(safe_events).hexdigest(),
            },
            "final_event_chain_sha256": records[-1].sha256 if records else None,
        }
    )
    entries = {
        "manifest.json": manifest,
        "safe-events.jsonl": safe_events,
        "integrity.json": integrity,
    }
    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED, compresslevel=9, strict_timestamps=True) as archive:
        for name in _ARCHIVE_FILENAMES:
            entry = ZipInfo(filename=name, date_time=_ARCHIVE_TIMESTAMP)
            entry.create_system = 3
            entry.external_attr = 0o600 << 16
            entry.compress_type = ZIP_DEFLATED
            archive.writestr(entry, entries[name], compress_type=ZIP_DEFLATED, compresslevel=9)
    return buffer.getvalue()


def _encrypt_archive(archive: bytes, recipient: SupportRecipient) -> bytes:
    ephemeral_private_key = X25519PrivateKey.generate()
    ephemeral_public_key = base64.b64encode(ephemeral_private_key.public_key().public_bytes_raw()).decode(
        "ascii"
    )
    nonce = base64.b64encode(os.urandom(12)).decode("ascii")
    content_key = _derive_content_key(
        ephemeral_private_key.exchange(recipient.public_key), recipient.key_id
    )
    aad = _canonical_header(recipient.key_id, ephemeral_public_key, nonce)
    ciphertext = AESGCM(content_key).encrypt(base64.b64decode(nonce), archive, aad)
    envelope = {
        "schema": _ENVELOPE_SCHEMA,
        "recipient_key_id": recipient.key_id,
        "ephemeral_public_key": ephemeral_public_key,
        "nonce": nonce,
        "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
        "ciphertext_sha256": hashlib.sha256(ciphertext).hexdigest(),
    }
    return canonical_json_bytes(envelope)


def _derive_content_key(shared_secret: bytes, recipient_key_id: str) -> bytes:
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b"ffpdiag/1|" + recipient_key_id.encode("utf-8"),
    ).derive(shared_secret)


def _canonical_header(recipient_key_id: str, ephemeral_public_key: str, nonce: str) -> bytes:
    return canonical_json_bytes(
        {
            "schema": _ENVELOPE_SCHEMA,
            "recipient_key_id": recipient_key_id,
            "ephemeral_public_key": ephemeral_public_key,
            "nonce": nonce,
        }
    )


def _validate_destination(destination: Path) -> None:
    if destination.suffix != ".ffpdiag":
        raise ValueError("diagnostic destination must use the .ffpdiag suffix")
    if not destination.parent.is_dir():
        raise ValueError("diagnostic destination directory does not exist")


def _publish_private_envelope(destination: Path, envelope: bytes) -> None:
    temporary = destination.parent / f".ffpdiag-{secrets.token_hex(16)}"
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            _set_private_file_mode(temporary, descriptor)
            with os.fdopen(descriptor, "wb", closefd=False) as handle:
                handle.write(envelope)
                handle.flush()
                os.fsync(handle.fileno())
        finally:
            os.close(descriptor)
        os.replace(temporary, destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _set_private_file_mode(path: Path, descriptor: int) -> None:
    """Restrict the diagnostic file to owner-only on POSIX; best-effort on Windows.

    POSIX: ``fchmod`` pins the descriptor to 0o600 (the file is already created
    0o600 via ``os.open``, so this is belt-and-suspenders against a loose umask).
    Windows: ``os.fchmod`` is unavailable, so we fall back to ``os.chmod``, which
    only toggles the read-only attribute and does NOT establish an owner-only
    ACL — the inherited directory ACL governs real access. Privacy on Windows
    therefore rests on the envelope encryption, not the on-disk file mode.
    """
    fchmod = getattr(os, "fchmod", None)
    if fchmod is None:
        os.chmod(path, 0o600)
        return
    fchmod(descriptor, 0o600)


def _decode_base64(value: str) -> bytes:
    return base64.b64decode(value.encode("ascii"), validate=True)


def _require_string(envelope: dict[str, object], name: str) -> str:
    value = envelope[name]
    if not isinstance(value, str):
        raise ValueError(f"ffpdiag envelope field {name} must be a string")
    return value
