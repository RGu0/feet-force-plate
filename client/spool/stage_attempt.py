"""Encrypted temporary storage for one discardable operator-started stage."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import shutil
import uuid

from client.device.protocol import RawFrame

from .segments import ImmutableSegmentWriter, SealedSegment, _fsync_directory, read_segment
from .state_store import KeyProvider


_SEALED_ATTEMPT_PROVENANCE = object()
_SEALED_ATTEMPT_FACTORY_CAPABILITY = object()


@dataclass(frozen=True, slots=True, init=False)
class SealedStageAttempt:
    """Authenticated frames whose provenance is bound to one stage attempt."""

    session_id: str
    stage_id: str
    attempt_id: str
    frames: tuple[RawFrame, ...]
    segment_ids: tuple[str, ...]
    ciphertext_sha256: tuple[str, ...]
    _provenance: object = field(repr=False, compare=False)

    def __init__(
        self,
        *,
        session_id: str,
        stage_id: str,
        attempt_id: str,
        frames: tuple[RawFrame, ...],
    ) -> None:
        _ = session_id, stage_id, attempt_id, frames
        raise TypeError("SealedStageAttempt instances are created only StageAttemptSpool.seal")

    @classmethod
    def _from_verified_attempt(
        cls,
        *,
        session_id: str,
        stage_id: str,
        attempt_id: str,
        frames: tuple[RawFrame, ...],
        sealed_segments: tuple[SealedSegment, ...],
        _factory_capability: object,
    ) -> SealedStageAttempt:
        if _factory_capability is not _SEALED_ATTEMPT_FACTORY_CAPABILITY:
            raise TypeError("sealed stage attempts require StageAttemptSpool.seal")
        instance = object.__new__(cls)
        object.__setattr__(instance, "session_id", session_id)
        object.__setattr__(instance, "stage_id", stage_id)
        object.__setattr__(instance, "attempt_id", attempt_id)
        object.__setattr__(instance, "frames", frames)
        object.__setattr__(
            instance,
            "segment_ids",
            tuple(segment.segment_id for segment in sealed_segments),
        )
        object.__setattr__(
            instance,
            "ciphertext_sha256",
            tuple(segment.ciphertext_sha256 for segment in sealed_segments),
        )
        object.__setattr__(instance, "_provenance", _SEALED_ATTEMPT_PROVENANCE)
        return instance

    def _has_verified_provenance(self) -> bool:
        return self._provenance is _SEALED_ATTEMPT_PROVENANCE


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
        self._stage_id = stage_id
        self._attempt_id = str(uuid.uuid4())
        self._key_provider = key_provider
        self._staging_directory = (
            Path(root)
            / ".stage-attempts"
            / session_id
            / stage_id
            / self._attempt_id
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
        self._sealed_attempt: SealedStageAttempt | None = None
        self._discarded = False

    @property
    def staging_directory(self) -> Path:
        return self._staging_directory

    def append(self, frame: RawFrame) -> None:
        if self._discarded:
            raise RuntimeError("stage attempt has been discarded")
        if self._sealed_attempt is not None:
            raise RuntimeError("stage attempt has already been sealed")
        sealed = self._writer.append(frame)
        self._has_open_frames = sealed is None
        if sealed is not None:
            self._sealed_segments.append(sealed)

    def seal(self) -> SealedStageAttempt:
        """Close and return the authenticated provenance-bound stage result."""

        if self._discarded:
            raise RuntimeError("stage attempt has been discarded")
        if self._sealed_attempt is not None:
            return self._sealed_attempt
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
        self._sealed_attempt = SealedStageAttempt._from_verified_attempt(
            session_id=self._session_id,
            stage_id=self._stage_id,
            attempt_id=self._attempt_id,
            frames=tuple(frames),
            sealed_segments=tuple(self._sealed_segments),
            _factory_capability=_SEALED_ATTEMPT_FACTORY_CAPABILITY,
        )
        return self._sealed_attempt

    def discard(self, *, reason: str) -> None:
        if self._discarded:
            raise RuntimeError("stage attempt has been discarded")
        if not reason:
            raise ValueError("discard reason is required")
        self._discarded = True
        if self._staging_directory.exists():
            shutil.rmtree(self._staging_directory)
            _fsync_directory(self._staging_directory.parent)
