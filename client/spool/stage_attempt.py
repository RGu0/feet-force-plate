"""Encrypted temporary storage for one discardable operator-started stage."""

from __future__ import annotations

from pathlib import Path
import shutil
import uuid

from client.device.protocol import RawFrame

from .segments import ImmutableSegmentWriter, SealedSegment, _fsync_directory, read_segment
from .state_store import KeyProvider


class StageAttemptSpool:
    """Keep one stage attempt independently discardable until it is merged."""

    def __init__(
        self,
        root: str | Path,
        *,
        session_id: str,
        stage_id: str,
        key_provider: KeyProvider,
        versions: dict[str, str],
        segment_duration_seconds: float = 5.0,
    ) -> None:
        if not session_id or not stage_id or not versions:
            raise ValueError("stage-attempt identity and versions are required")
        self._session_id = session_id
        self._key_provider = key_provider
        self._staging_directory = (
            Path(root)
            / ".stage-attempts"
            / session_id
            / stage_id
            / str(uuid.uuid4())
        )
        self._writer = ImmutableSegmentWriter(
            self._staging_directory,
            session_id=session_id,
            key_provider=key_provider,
            versions=versions,
            segment_duration_seconds=segment_duration_seconds,
        )
        self._sealed_segments: list[SealedSegment] = []
        self._has_open_frames = False
        self._sealed_frames: tuple[RawFrame, ...] | None = None
        self._discarded = False

    @property
    def staging_directory(self) -> Path:
        return self._staging_directory

    def append(self, frame: RawFrame) -> None:
        if self._discarded:
            raise RuntimeError("stage attempt has been discarded")
        if self._sealed_frames is not None:
            raise RuntimeError("stage attempt has already been sealed")
        sealed = self._writer.append(frame)
        self._has_open_frames = sealed is None
        if sealed is not None:
            self._sealed_segments.append(sealed)

    def seal(self) -> tuple[RawFrame, ...]:
        """Close, authenticate, decrypt, and return this attempt's ordered frames."""

        if self._discarded:
            raise RuntimeError("stage attempt has been discarded")
        if self._sealed_frames is not None:
            return self._sealed_frames
        if self._has_open_frames:
            self._sealed_segments.append(self._writer.close())
            self._has_open_frames = False
        if not self._sealed_segments:
            raise ValueError("cannot seal a stage attempt without frames")
        frames: list[RawFrame] = []
        for sealed in sorted(self._sealed_segments, key=lambda item: item.segment_index):
            restored = read_segment(sealed.path, self._key_provider)
            if restored.session_id != self._session_id:
                raise ValueError("stage attempt segment session identity mismatch")
            frames.extend(restored.frames)
        self._sealed_frames = tuple(frames)
        return self._sealed_frames

    def discard(self, *, reason: str) -> None:
        if self._discarded:
            raise RuntimeError("stage attempt has been discarded")
        if not reason:
            raise ValueError("discard reason is required")
        self._discarded = True
        if self._staging_directory.exists():
            shutil.rmtree(self._staging_directory)
            _fsync_directory(self._staging_directory.parent)
