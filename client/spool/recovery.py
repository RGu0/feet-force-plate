"""Filesystem/SQLite reconciliation for immutable local segments."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from .segments import (
    ImmutableSegmentWriter,
    SealedSegment,
    SegmentIntegrityError,
    read_segment,
)
from .state_store import KeyProvider, StateStore


@dataclass(frozen=True, slots=True)
class ScanResult:
    temporary_recovered: int = 0
    temporary_quarantined: int = 0
    sealed_quarantined: int = 0
    orphan_segments_registered: int = 0
    sessions_marked_incomplete: int = 0
    uploads_requeued: int = 0


@dataclass(frozen=True, slots=True)
class CleanupResult:
    files_deleted: int = 0
    records_finalized: int = 0


def _register_path(
    path: Path,
    restored,
    store: StateStore,
    repository_root: Path,
) -> None:
    store.register_sealed_segment(
        restored.segment_id,
        session_id=restored.session_id,
        relative_path=str(path.relative_to(repository_root)),
        byte_count=path.stat().st_size,
        sealed_at_ns=restored.frames[-1].host_wall_time_ns,
    )


def _fsync_directory(path: Path) -> None:
    directory_fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _quarantine(path: Path) -> None:
    quarantine = path.parent / "quarantine"
    quarantine.mkdir(exist_ok=True)
    os.replace(path, quarantine / f"{path.name}.corrupt")
    _fsync_directory(path.parent)
    _fsync_directory(quarantine)


def seal_and_register(
    writer: ImmutableSegmentWriter,
    store: StateStore,
    repository_root: str | Path,
) -> SealedSegment:
    """Close/fsync/rename first, then atomically register SEALED + PENDING."""

    sealed = writer.close()
    restored = writer.verify(sealed)
    _register_path(sealed.path, restored, store, Path(repository_root))
    return sealed


def cleanup_acknowledged_segments(
    store: StateStore,
    repository_root: str | Path,
    *,
    now_ns: int,
) -> CleanupResult:
    """Delete only eligible acknowledged files, then finalize their DB records.

    A crash after unlink but before SQLite finalization is safe: a subsequent run
    sees the eligible record, observes the missing file, and finalizes that record.
    A deletion error is propagated before the record can be removed.
    """

    root = Path(repository_root).resolve()
    files_deleted = 0
    records_finalized = 0
    for candidate in store.cleanup_candidates(now_ns=now_ns):
        path = (root / candidate.relative_path).resolve()
        if root not in path.parents:
            raise ValueError("cleanup candidate escapes the configured repository root")
        if path.exists():
            path.unlink()
            _fsync_directory(path.parent)
            files_deleted += 1
        store.finalize_segment_cleanup(candidate.segment_id, now_ns=now_ns)
        records_finalized += 1
    return CleanupResult(
        files_deleted=files_deleted,
        records_finalized=records_finalized,
    )


class RecoveryScanner:
    def __init__(
        self,
        segment_root: str | Path,
        store: StateStore,
        key_provider: KeyProvider,
        repository_root: str | Path,
    ) -> None:
        self._segment_root = Path(segment_root)
        self._store = store
        self._key_provider = key_provider
        self._repository_root = Path(repository_root)

    def scan(self, *, recovered_at_ns: int) -> ScanResult:
        self._segment_root.mkdir(parents=True, exist_ok=True)
        recovered = 0
        quarantined = 0
        sealed_quarantined = 0
        registered = 0
        for temporary in sorted(self._segment_root.rglob("*.tmp")):
            try:
                restored = read_segment(temporary, self._key_provider)
            except SegmentIntegrityError:
                _quarantine(temporary)
                quarantined += 1
                continue
            final = temporary.with_suffix(".ffps")
            os.replace(temporary, final)
            _fsync_directory(final.parent)
            _register_path(final, restored, self._store, self._repository_root)
            recovered += 1
        for path in sorted(self._segment_root.rglob("*.ffps")):
            try:
                restored = read_segment(path, self._key_provider)
            except SegmentIntegrityError:
                relative_path = str(path.relative_to(self._repository_root))
                _quarantine(path)
                self._store.quarantine_segment_path(relative_path)
                sealed_quarantined += 1
                continue
            if not self._store.segment_exists(restored.segment_id):
                _register_path(path, restored, self._store, self._repository_root)
                registered += 1
        interrupted = self._store.recover_interrupted_state(
            recovered_at_ns=recovered_at_ns
        )
        return ScanResult(
            temporary_recovered=recovered,
            temporary_quarantined=quarantined,
            sealed_quarantined=sealed_quarantined,
            orphan_segments_registered=registered,
            sessions_marked_incomplete=interrupted.sessions_marked_incomplete,
            uploads_requeued=interrupted.uploads_requeued,
        )
