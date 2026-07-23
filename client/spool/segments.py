"""Versioned, compressed, authenticated immutable raw-frame segments."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
import os
from pathlib import Path
import struct
import uuid
import zlib

import numpy as np
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from client.device.protocol import RawFrame
from .state_store import KeyProvider


MAGIC = b"FFPSSEG1"
TAIL = b"FFPSEND1"
CONTAINER_VERSION = "ffps-segment/1"

_SUPPORTED_VALUE_DTYPES = {
    np.dtype(np.uint8): ("uint8", np.dtype("u1")),
    np.dtype(np.uint16): ("uint16-le", np.dtype("<u2")),
}


class SegmentIntegrityError(ValueError):
    """A segment is truncated, malformed, unauthenticated, or digest-invalid."""


@dataclass(frozen=True, slots=True)
class SealedSegment:
    segment_id: str
    segment_index: int
    path: Path
    frame_count: int
    first_source_index: int
    last_source_index: int
    nonce: bytes
    ciphertext_sha256: str
    byte_count: int


@dataclass(frozen=True, slots=True)
class RestoredSegment:
    session_id: str
    segment_id: str
    segment_index: int
    frames: tuple[RawFrame, ...]
    versions: dict[str, str]
    quality_flags: frozenset[str]
    ciphertext_sha256: str


def _canonical_json(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


class ImmutableSegmentWriter:
    """Collects one 5-10 second raw segment and closes it atomically."""

    def __init__(
        self,
        root: str | Path,
        *,
        session_id: str,
        key_provider: KeyProvider,
        versions: dict[str, str],
        segment_duration_seconds: float,
        target_plaintext_bytes: int = 8 * 1024 * 1024,
        starting_segment_index: int = 0,
    ) -> None:
        if not 5.0 <= segment_duration_seconds <= 10.0:
            raise ValueError("segment duration must be between 5 and 10 seconds")
        if target_plaintext_bytes <= 0:
            raise ValueError("target_plaintext_bytes must be positive")
        if not session_id or not versions or any(not key or not value for key, value in versions.items()):
            raise ValueError("session_id and explicit versions are required")
        self._root = Path(root)
        self._session_id = session_id
        self._key_provider = key_provider
        self._versions = dict(versions)
        self._duration_ns = round(segment_duration_seconds * 1_000_000_000)
        self._target_bytes = target_plaintext_bytes
        self._segment_index = starting_segment_index
        self._frames: list[RawFrame] = []

    def append(self, frame: RawFrame) -> SealedSegment | None:
        value_dtype = _storage_dtype(frame.values.dtype)
        if frame.values.shape != (48, 64) or value_dtype is None:
            raise ValueError("segment frames must be 48x64 uint8 or uint16")
        if self._frames and _storage_dtype(self._frames[0].values.dtype) != value_dtype:
            raise ValueError("raw value dtype must not change within an immutable segment")
        if self._frames and frame.source_index <= self._frames[-1].source_index:
            raise ValueError("source_index must increase strictly within a session")
        self._frames.append(frame)
        duration = frame.host_monotonic_ns - self._frames[0].host_monotonic_ns
        raw_bytes = len(self._frames) * 48 * 64 * value_dtype.itemsize
        if duration >= self._duration_ns or raw_bytes >= self._target_bytes:
            return self.close()
        return None

    def close(self) -> SealedSegment:
        if not self._frames:
            raise ValueError("cannot seal an empty segment")
        stored_dtype = _storage_dtype(self._frames[0].values.dtype)
        if stored_dtype is None:
            raise ValueError("segment frames must use a supported raw dtype")
        value_encoding = _value_encoding(stored_dtype)
        segment_id = str(uuid.uuid4())
        nonce = os.urandom(12)
        frame_metadata = [
            {
                "host_monotonic_ns": frame.host_monotonic_ns,
                "host_wall_time_ns": frame.host_wall_time_ns,
                "quality_flags": sorted(frame.quality_flags),
                "source_index": frame.source_index,
            }
            for frame in self._frames
        ]
        quality = sorted(
            {flag for frame in self._frames for flag in frame.quality_flags}
        )
        header = {
            "compression": "zlib",
            "container_version": CONTAINER_VERSION,
            "encryption": "AES-256-GCM",
            "frame_count": len(self._frames),
            "frames": frame_metadata,
            "matrix_shape": [48, 64],
            "nonce_hex": nonce.hex(),
            "quality_flags": quality,
            "segment_id": segment_id,
            "segment_index": self._segment_index,
            "session_id": self._session_id,
            "value_dtype": value_encoding,
            "versions": self._versions,
        }
        header_bytes = _canonical_json(header)
        raw = b"".join(
            frame.values.astype(stored_dtype, copy=False).tobytes(order="C")
            for frame in self._frames
        )
        compressed = zlib.compress(raw, level=6)
        key = self._key_provider.get_key()
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
        session_dir = self._root / self._session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        stem = f"segment-{self._segment_index:06d}-{segment_id}"
        temporary = session_dir / f"{stem}.tmp"
        final = session_dir / f"{stem}.ffps"
        with temporary.open("xb") as handle:
            handle.write(container)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, final)
        directory_fd = os.open(session_dir, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        frames = self._frames
        self._frames = []
        sealed = SealedSegment(
            segment_id=segment_id,
            segment_index=self._segment_index,
            path=final,
            frame_count=len(frames),
            first_source_index=frames[0].source_index,
            last_source_index=frames[-1].source_index,
            nonce=nonce,
            ciphertext_sha256=digest.hex(),
            byte_count=len(container),
        )
        self._segment_index += 1
        return sealed

    def verify(self, sealed: SealedSegment) -> RestoredSegment:
        """Verify a just-sealed file with the same secure key boundary."""

        return read_segment(sealed.path, self._key_provider)


def read_segment(path: str | Path, key_provider: KeyProvider) -> RestoredSegment:
    payload = Path(path).read_bytes()
    try:
        if payload[:8] != MAGIC or payload[-8:] != TAIL:
            raise SegmentIntegrityError("segment magic/tail mismatch")
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
            raise SegmentIntegrityError("segment length mismatch")
        observed = hashlib.sha256(ciphertext).digest()
        if not hmac.compare_digest(observed, digest):
            raise SegmentIntegrityError("ciphertext SHA-256 mismatch")
        header = json.loads(header_bytes)
        stored_dtype = _dtype_from_encoding(header["value_dtype"])
        key = key_provider.get_key()
        compressed = AESGCM(key).decrypt(
            bytes.fromhex(header["nonce_hex"]), ciphertext, header_bytes
        )
        raw = zlib.decompress(compressed)
    except SegmentIntegrityError:
        raise
    except (InvalidTag, KeyError, ValueError, struct.error, zlib.error, json.JSONDecodeError) as exc:
        raise SegmentIntegrityError(f"segment verification failed: {type(exc).__name__}") from exc
    expected = int(header["frame_count"]) * 48 * 64 * stored_dtype.itemsize
    if len(raw) != expected or len(header["frames"]) != header["frame_count"]:
        raise SegmentIntegrityError("frame payload length mismatch")
    frames = []
    width = 48 * 64 * stored_dtype.itemsize
    for index, metadata in enumerate(header["frames"]):
        values = np.frombuffer(
            raw[index * width : (index + 1) * width], dtype=stored_dtype
        ).copy()
        values = values.reshape(48, 64)
        values.setflags(write=False)
        frames.append(
            RawFrame(
                values=values,
                host_monotonic_ns=int(metadata["host_monotonic_ns"]),
                host_wall_time_ns=int(metadata["host_wall_time_ns"]),
                source_index=int(metadata["source_index"]),
                device_frame_seq=None,
                device_timestamp_ns=None,
                quality_flags=frozenset(metadata["quality_flags"]),
            )
        )
    return RestoredSegment(
        session_id=str(header["session_id"]),
        segment_id=str(header["segment_id"]),
        segment_index=int(header["segment_index"]),
        frames=tuple(frames),
        versions={str(k): str(v) for k, v in header["versions"].items()},
        quality_flags=frozenset(header["quality_flags"]),
        ciphertext_sha256=digest.hex(),
    )


def _storage_dtype(dtype: np.dtype) -> np.dtype | None:
    return _SUPPORTED_VALUE_DTYPES.get(np.dtype(dtype), (None, None))[1]


def _value_encoding(dtype: np.dtype) -> str:
    for candidate, (encoding, stored_dtype) in _SUPPORTED_VALUE_DTYPES.items():
        if stored_dtype == dtype:
            return encoding
    raise ValueError("unsupported raw value dtype")


def _dtype_from_encoding(value: object) -> np.dtype:
    for encoding, dtype in _SUPPORTED_VALUE_DTYPES.values():
        if value == encoding:
            return dtype
    raise SegmentIntegrityError("unsupported raw value dtype")


def write_session_manifest(
    root: str | Path,
    *,
    session_id: str,
    segment_paths: list[Path],
    key_provider: KeyProvider,
    local_quality_outcome: str,
    artifacts: list[dict[str, object]] | None = None,
) -> dict:
    if not segment_paths or not local_quality_outcome:
        raise ValueError("segments and local quality outcome are required")
    restored = [read_segment(path, key_provider) for path in segment_paths]
    restored.sort(key=lambda item: item.segment_index)
    if any(item.session_id != session_id for item in restored):
        raise ValueError("manifest cannot mix sessions")
    if [item.segment_index for item in restored] != list(range(len(restored))):
        raise ValueError("segment indexes must be contiguous from zero")
    versions = restored[0].versions
    if any(item.versions != versions for item in restored):
        raise ValueError("segment version snapshots differ within session")
    content = {
        "manifest_version": "ffps-session-manifest/1",
        "session_id": session_id,
        "local_quality_outcome": local_quality_outcome,
        "total_frames": sum(len(item.frames) for item in restored),
        "versions": versions,
        "segments": [
            {
                "ciphertext_sha256": item.ciphertext_sha256,
                "first_source_index": item.frames[0].source_index,
                "frame_count": len(item.frames),
                "last_source_index": item.frames[-1].source_index,
                "segment_id": item.segment_id,
                "segment_index": item.segment_index,
            }
            for item in restored
        ],
        "artifacts": artifacts or [],
    }
    content["manifest_sha256"] = hashlib.sha256(_canonical_json(content)).hexdigest()
    session_dir = Path(root) / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    temporary = session_dir / "manifest.tmp"
    final = session_dir / "manifest.json"
    with temporary.open("xb") as handle:
        handle.write(_canonical_json(content))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, final)
    return content
