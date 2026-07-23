"""Encrypted immutable derived hardware observations for already-valid sessions."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import struct
import uuid
import zlib

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from client.hardware_standardization.models import PhysicalArraySession

from .state_store import KeyProvider


MAGIC = b"FFPSDER1"
TAIL = b"FFPSDEND"
CONTAINER_VERSION = "ffps-derived-observation/1"
DERIVED_SCHEMA_VERSION = "hardware-derived-observation/1"


class DerivedArtifactIntegrityError(ValueError):
    """A derived observation is truncated, malformed, or unauthenticated."""


@dataclass(frozen=True, slots=True)
class DerivedArtifact:
    artifact_id: str
    kind: str
    schema_version: str
    path: Path
    ciphertext_sha256: str
    byte_count: int


def _canonical_json(payload: dict[str, object]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _derived_payload(
    session: PhysicalArraySession, *, processing_metadata: dict[str, object] | None
) -> dict[str, object]:
    """Keep raw matrices in their raw segments; save only repaired/derived values here."""

    return {
        "schema_version": DERIVED_SCHEMA_VERSION,
        "source_schema_version": session.schema_version,
        "session_id": session.session_id,
        "coordinate_frame": session.coordinate_frame,
        "coordinate_unit": session.coordinate_unit,
        "force_unit": session.force_unit,
        "measurement_profile": {
            "profile_version": session.measurement_profile.profile_version,
            "geometry_validation": session.measurement_profile.geometry_validation,
            "baseline_validation": session.measurement_profile.baseline_validation,
            "force_validation": session.measurement_profile.force_validation,
            "timing_validation": session.measurement_profile.timing_validation,
            "active_area_validation": session.measurement_profile.active_area_validation,
            "uncertainty_profile_version": session.measurement_profile.uncertainty_profile_version,
        },
        "cells": [
            {
                "cell_id": cell.cell_id,
                "source_index": cell.source_index,
                "board_x_mm": cell.board_x_mm,
                "board_y_mm": cell.board_y_mm,
                "status": cell.status.value,
            }
            for cell in session.cells
        ],
        "frames": [
            {
                "timestamp_s": frame.timestamp_s,
                "zero_corrected_count": (
                    None
                    if frame.zero_corrected_count is None
                    else list(frame.zero_corrected_count)
                ),
                "relative_load_count": (
                    None
                    if frame.relative_load_count is None
                    else list(frame.relative_load_count)
                ),
                "repaired_count": (
                    None if frame.repaired_count is None else list(frame.repaired_count)
                ),
                "repaired_cell_mask": (
                    None
                    if frame.repaired_cell_mask is None
                    else list(frame.repaired_cell_mask)
                ),
                "estimated_force_n": (
                    None
                    if frame.estimated_force_n is None
                    else list(frame.estimated_force_n)
                ),
                "quality": frame.quality.value,
                "quality_flags": sorted(frame.quality_flags),
            }
            for frame in session.frames
        ],
        "provenance": {
            "adapter_version": session.adapter_version,
            "geometry_version": session.geometry_version,
            "source_schema_version": session.source_schema_version,
        },
        "hardware_processing": processing_metadata or {},
    }


def write_derived_observation(
    root: str | Path,
    *,
    session: PhysicalArraySession,
    key_provider: KeyProvider,
    processing_metadata: dict[str, object] | None = None,
) -> DerivedArtifact:
    """Write one authenticated V1 derived observation beside temporary raw segments."""

    if not session.frames:
        raise ValueError("derived observation requires at least one frame")
    artifact_id = str(uuid.uuid4())
    nonce = os.urandom(12)
    header = {
        "artifact_id": artifact_id,
        "container_version": CONTAINER_VERSION,
        "encryption": "AES-256-GCM",
        "kind": "HARDWARE_DERIVED_OBSERVATION",
        "nonce_hex": nonce.hex(),
        "schema_version": DERIVED_SCHEMA_VERSION,
        "session_id": session.session_id,
    }
    header_bytes = _canonical_json(header)
    compressed = zlib.compress(
        _canonical_json(
            _derived_payload(session, processing_metadata=processing_metadata)
        ),
        level=6,
    )
    key = key_provider.get_key()
    if len(key) != 32:
        raise ValueError("OS key provider must return a 32-byte AES-256 key")
    ciphertext = AESGCM(key).encrypt(nonce, compressed, header_bytes)
    digest = hashlib.sha256(ciphertext).digest()
    container = b"".join(
        (
            MAGIC,
            struct.pack(">I", len(header_bytes)),
            header_bytes,
            struct.pack(">Q", len(ciphertext)),
            ciphertext,
            digest,
            TAIL,
        )
    )
    session_directory = Path(root) / session.session_id
    session_directory.mkdir(parents=True, exist_ok=True)
    temporary = session_directory / f"derived-{artifact_id}.tmp"
    final = session_directory / f"derived-{artifact_id}.ffpd"
    with temporary.open("xb") as handle:
        handle.write(container)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, final)
    return DerivedArtifact(
        artifact_id=artifact_id,
        kind="HARDWARE_DERIVED_OBSERVATION",
        schema_version=DERIVED_SCHEMA_VERSION,
        path=final,
        ciphertext_sha256=digest.hex(),
        byte_count=len(container),
    )


def read_derived_observation(path: str | Path, *, key_provider: KeyProvider) -> dict[str, object]:
    """Verify and decrypt a derived observation for a hardware/algorithm handoff."""

    payload = Path(path).read_bytes()
    try:
        if payload[:8] != MAGIC or payload[-8:] != TAIL:
            raise DerivedArtifactIntegrityError("derived artifact magic/tail mismatch")
        offset = 8
        header_length = struct.unpack(">I", payload[offset : offset + 4])[0]
        offset += 4
        header_bytes = payload[offset : offset + header_length]
        offset += header_length
        ciphertext_length = struct.unpack(">Q", payload[offset : offset + 8])[0]
        offset += 8
        ciphertext = payload[offset : offset + ciphertext_length]
        offset += ciphertext_length
        digest = payload[offset : offset + 32]
        if offset + 32 + 8 != len(payload):
            raise DerivedArtifactIntegrityError("derived artifact length mismatch")
        if hashlib.sha256(ciphertext).digest() != digest:
            raise DerivedArtifactIntegrityError("derived artifact ciphertext digest mismatch")
        header = json.loads(header_bytes)
        if header["container_version"] != CONTAINER_VERSION:
            raise DerivedArtifactIntegrityError("unsupported derived artifact version")
        key = key_provider.get_key()
        if len(key) != 32:
            raise ValueError("OS key provider must return a 32-byte AES-256 key")
        compressed = AESGCM(key).decrypt(
            bytes.fromhex(header["nonce_hex"]), ciphertext, header_bytes
        )
        decoded = json.loads(zlib.decompress(compressed))
    except DerivedArtifactIntegrityError:
        raise
    except (InvalidTag, KeyError, ValueError, struct.error, zlib.error, json.JSONDecodeError) as exc:
        raise DerivedArtifactIntegrityError(
            f"derived artifact verification failed: {type(exc).__name__}"
        ) from exc
    if not isinstance(decoded, dict) or decoded.get("schema_version") != DERIVED_SCHEMA_VERSION:
        raise DerivedArtifactIntegrityError("derived observation schema mismatch")
    return decoded
