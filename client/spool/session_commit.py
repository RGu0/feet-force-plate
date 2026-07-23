"""Validity-gated promotion from temporary capture data to a local session."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil

from client.device.protocol import RawFrame

from .segments import ImmutableSegmentWriter, SealedSegment, write_session_manifest
from .state_store import KeyProvider, StateStore, ValidSegmentRecord


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@dataclass(frozen=True, slots=True)
class CommittedValidSession:
    session_id: str
    total_frames: int
    manifest_sha256: str
    session_directory: Path


class ValidSessionStager:
    """Keeps capture bytes temporary until the whole session is accepted."""

    def __init__(
        self,
        root: str | Path,
        *,
        session_id: str,
        key_provider: KeyProvider,
        store: StateStore,
        subject_uuid: str,
        consent_id: str | None,
        versions: dict[str, str],
        started_at_ns: int,
        segment_duration_seconds: float = 5.0,
    ) -> None:
        if not session_id or not subject_uuid or not versions:
            raise ValueError("session identity and versions are required")
        self._root = Path(root)
        self._staging_root = self._root / ".staging"
        self._sessions_root = self._root / "sessions"
        self._session_id = session_id
        self._key_provider = key_provider
        self._store = store
        self._subject_uuid = subject_uuid
        self._consent_id = consent_id
        self._versions = dict(versions)
        self._started_at_ns = started_at_ns
        self._writer = ImmutableSegmentWriter(
            self._staging_root,
            session_id=session_id,
            key_provider=key_provider,
            versions=versions,
            segment_duration_seconds=segment_duration_seconds,
        )
        self._sealed: list[SealedSegment] = []
        self._has_open_frames = False
        self._finished = False

    @property
    def staging_directory(self) -> Path:
        return self._staging_root / self._session_id

    def append(self, frame: RawFrame) -> None:
        if self._finished:
            raise RuntimeError("session staging is already finished")
        sealed = self._writer.append(frame)
        self._has_open_frames = sealed is None
        if sealed is not None:
            self._sealed.append(sealed)

    def discard(self, *, reason: str) -> None:
        if self._finished:
            raise RuntimeError("session staging is already finished")
        if not reason:
            raise ValueError("discard reason is required")
        self._finished = True
        if self.staging_directory.exists():
            shutil.rmtree(self.staging_directory)
            _fsync_directory(self._staging_root)

    def commit_valid(self, *, ended_at_ns: int) -> CommittedValidSession:
        if self._finished:
            raise RuntimeError("session staging is already finished")
        if self._has_open_frames:
            self._sealed.append(self._writer.close())
            self._has_open_frames = False
        if not self._sealed:
            raise ValueError("cannot commit a session without frames")
        manifest = write_session_manifest(
            self._staging_root,
            session_id=self._session_id,
            segment_paths=[segment.path for segment in self._sealed],
            key_provider=self._key_provider,
            local_quality_outcome="VALID",
        )
        staging = self.staging_directory
        final = self._sessions_root / self._session_id
        if final.exists():
            raise FileExistsError(f"local session already exists: {self._session_id}")
        self._sessions_root.mkdir(parents=True, exist_ok=True)
        os.replace(staging, final)
        _fsync_directory(self._staging_root)
        _fsync_directory(self._sessions_root)
        records = tuple(
            ValidSegmentRecord(
                segment_id=segment.segment_id,
                relative_path=str((Path("sessions") / self._session_id / segment.path.name)),
                byte_count=segment.byte_count,
                sealed_at_ns=ended_at_ns,
            )
            for segment in self._sealed
        )
        try:
            self._store.commit_valid_session(
                self._session_id,
                subject_uuid=self._subject_uuid,
                consent_id=self._consent_id,
                versions_json=json.dumps(self._versions, sort_keys=True).encode("utf-8"),
                started_at_ns=self._started_at_ns,
                ended_at_ns=ended_at_ns,
                manifest_sha256=str(manifest["manifest_sha256"]),
                segments=records,
            )
        except Exception:
            os.replace(final, staging)
            _fsync_directory(self._sessions_root)
            _fsync_directory(self._staging_root)
            raise
        self._finished = True
        return CommittedValidSession(
            session_id=self._session_id,
            total_frames=int(manifest["total_frames"]),
            manifest_sha256=str(manifest["manifest_sha256"]),
            session_directory=final,
        )

    @classmethod
    def discard_interrupted_staging(cls, root: str | Path) -> int:
        staging_root = Path(root) / ".staging"
        if not staging_root.exists():
            return 0
        count = 0
        for directory in staging_root.iterdir():
            if directory.is_dir():
                shutil.rmtree(directory)
                count += 1
        if count:
            _fsync_directory(staging_root)
        return count
