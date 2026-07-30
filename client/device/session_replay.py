"""Internal, read-only replay of one committed hardware session.

This module is intentionally a support/quality boundary, not a customer-facing
viewer.  It verifies the immutable session manifest and encrypted raw segments
before returning the same :class:`RawFrame` objects used by live acquisition.
Diagnostic summaries contain counts, versions and integrity events only; raw
pressure matrices never leave the replay object unless an internal caller
explicitly iterates its ``RawFrame`` source.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
from pathlib import Path
from typing import Final

from client.spool.derived_artifact import (
    DerivedArtifactIntegrityError,
    read_derived_observation,
)
from client.spool.segments import SegmentIntegrityError, read_segment
from client.spool.state_store import KeyProvider

from .protocol import RawFrame


_MANIFEST_VERSION: Final = "ffps-session-manifest/1"


class ReplayFailureCode(StrEnum):
    """Stable internal failure labels for support and automated reproduction."""

    MANIFEST_INVALID = "MANIFEST_INVALID"
    MISSING_SEGMENT = "MISSING_SEGMENT"
    SEGMENT_INVALID = "SEGMENT_INVALID"
    TIMELINE_INVALID = "TIMELINE_INVALID"
    DERIVED_ARTIFACT_INVALID = "DERIVED_ARTIFACT_INVALID"
    DEVICE_DISCONNECTED = "DEVICE_DISCONNECTED"
    CHECKSUM_ERROR = "CHECKSUM_ERROR"
    ALGORITHM_FAILURE = "ALGORITHM_FAILURE"


class ReplayVerificationError(ValueError):
    """A persisted session cannot safely be replayed."""

    def __init__(self, code: ReplayFailureCode, detail: str) -> None:
        super().__init__(f"{code.value}: {detail}")
        self.code = code


class ReplayInjectedFailure(RuntimeError):
    """A deterministic internal fault injected into a replay stream."""

    def __init__(self, code: ReplayFailureCode) -> None:
        super().__init__(code.value)
        self.code = code


@dataclass(frozen=True, slots=True)
class ReplayDiagnosticSummary:
    """Safe-to-export support metadata; deliberately contains no matrices or keys."""

    session_id: str
    manifest_sha256: str
    total_frames: int
    first_host_monotonic_ns: int
    last_host_monotonic_ns: int
    protocol_profile: str | None
    quality_event_count: int
    reconstructed_frame_count: int

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": "internal-hardware-replay-diagnostic/1",
            "session_id": self.session_id,
            "manifest_sha256": self.manifest_sha256,
            "total_frames": self.total_frames,
            "first_host_monotonic_ns": self.first_host_monotonic_ns,
            "last_host_monotonic_ns": self.last_host_monotonic_ns,
            "protocol_profile": self.protocol_profile,
            "quality_event_count": self.quality_event_count,
            "reconstructed_frame_count": self.reconstructed_frame_count,
        }


class InternalSessionReplay:
    """Verified in-memory ``RawFrame`` source for internal support workflows.

    ``speed`` is a caller-facing playback hint.  The source never sleeps: a UI
    or test clock may schedule frames using ``relative_time_s`` while a forensic
    caller can step through the same source deterministically.
    """

    def __init__(
        self,
        *,
        session_id: str,
        manifest_sha256: str,
        versions: dict[str, str],
        frames: tuple[RawFrame, ...],
        quality_event_count: int,
        reconstructed_frame_count: int,
    ) -> None:
        self.session_id = session_id
        self.manifest_sha256 = manifest_sha256
        self.versions = dict(versions)
        self._frames = frames
        self._quality_event_count = quality_event_count
        self._reconstructed_frame_count = reconstructed_frame_count

    @classmethod
    def open(
        cls, root: str | Path, *, session_id: str, key_provider: KeyProvider
    ) -> InternalSessionReplay:
        """Open only a fully verifiable, committed session under ``root/sessions``."""

        session_directory = Path(root) / "sessions" / session_id
        manifest_path = session_directory / "manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
            raise ReplayVerificationError(
                ReplayFailureCode.MANIFEST_INVALID, "manifest is unavailable"
            ) from exc
        _verify_manifest(manifest, session_id)
        expected_segments = manifest["segments"]
        assert isinstance(expected_segments, list)
        frames: list[RawFrame] = []
        for expected in expected_segments:
            assert isinstance(expected, dict)
            segment_id = str(expected["segment_id"])
            matches = tuple(session_directory.glob(f"segment-*-{segment_id}.ffps"))
            if len(matches) != 1:
                raise ReplayVerificationError(
                    ReplayFailureCode.MISSING_SEGMENT,
                    f"segment {segment_id} is missing or ambiguous",
                )
            try:
                restored = read_segment(matches[0], key_provider)
            except (OSError, SegmentIntegrityError, ValueError) as exc:
                raise ReplayVerificationError(
                    ReplayFailureCode.SEGMENT_INVALID,
                    f"segment {segment_id} failed authentication or decoding",
                ) from exc
            _verify_segment(restored, expected, session_id)
            frames.extend(restored.frames)
        _verify_timeline(frames, expected_total=int(manifest["total_frames"]))
        event_count, reconstructed_count = _read_quality_counts(
            session_directory, session_id, key_provider
        )
        versions = {str(key): str(value) for key, value in manifest["versions"].items()}
        return cls(
            session_id=session_id,
            manifest_sha256=str(manifest["manifest_sha256"]),
            versions=versions,
            frames=tuple(frames),
            quality_event_count=event_count,
            reconstructed_frame_count=reconstructed_count,
        )

    @property
    def total_frames(self) -> int:
        return len(self._frames)

    def diagnostic_summary(self) -> ReplayDiagnosticSummary:
        first, last = self._frames[0], self._frames[-1]
        return ReplayDiagnosticSummary(
            session_id=self.session_id,
            manifest_sha256=self.manifest_sha256,
            total_frames=len(self._frames),
            first_host_monotonic_ns=first.host_monotonic_ns,
            last_host_monotonic_ns=last.host_monotonic_ns,
            protocol_profile=self.versions.get("protocol_profile")
            or self.versions.get("protocol"),
            quality_event_count=self._quality_event_count,
            reconstructed_frame_count=self._reconstructed_frame_count,
        )

    def seek_source_index(self, source_index: int) -> int:
        """Return the frame offset at or immediately after a raw source index."""

        for offset, frame in enumerate(self._frames):
            if frame.source_index >= source_index:
                return offset
        return len(self._frames)

    def frames(
        self,
        *,
        start_source_index: int | None = None,
        end_source_index: int | None = None,
        loops: int = 1,
        speed: float = 1.0,
        inject_failure: ReplayFailureCode | None = None,
        fail_after_frames: int = 0,
    ) -> Iterator[RawFrame]:
        """Yield live-contract raw frames for step, range and loop playback.

        ``inject_failure`` supports repeatable support/quality tests.  It never
        modifies encrypted bytes or fabricates a raw frame; a consumer receives a
        stable failure at the selected frame boundary instead.
        """

        if loops <= 0:
            raise ValueError("loops must be positive")
        if speed <= 0:
            raise ValueError("speed must be positive")
        if fail_after_frames < 0:
            raise ValueError("fail_after_frames cannot be negative")
        selected = tuple(
            frame
            for frame in self._frames
            if (start_source_index is None or frame.source_index >= start_source_index)
            and (end_source_index is None or frame.source_index <= end_source_index)
        )
        emitted = 0
        for _ in range(loops):
            for frame in selected:
                if inject_failure is not None and emitted == fail_after_frames:
                    raise ReplayInjectedFailure(inject_failure)
                emitted += 1
                yield frame

    def relative_time_s(self, frame: RawFrame, *, speed: float = 1.0) -> float:
        """Return a caller-schedulable replay time from the first host timestamp."""

        if speed <= 0:
            raise ValueError("speed must be positive")
        return (frame.host_monotonic_ns - self._frames[0].host_monotonic_ns) / (
            1_000_000_000 * speed
        )


def _canonical_json(payload: dict[str, object]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _verify_manifest(manifest: object, session_id: str) -> None:
    if not isinstance(manifest, dict):
        raise ReplayVerificationError(ReplayFailureCode.MANIFEST_INVALID, "not an object")
    if manifest.get("manifest_version") != _MANIFEST_VERSION:
        raise ReplayVerificationError(ReplayFailureCode.MANIFEST_INVALID, "unsupported version")
    if manifest.get("session_id") != session_id:
        raise ReplayVerificationError(ReplayFailureCode.MANIFEST_INVALID, "session id mismatch")
    if not isinstance(manifest.get("segments"), list) or not manifest["segments"]:
        raise ReplayVerificationError(ReplayFailureCode.MANIFEST_INVALID, "segments missing")
    if not isinstance(manifest.get("versions"), dict) or not manifest["versions"]:
        raise ReplayVerificationError(ReplayFailureCode.MANIFEST_INVALID, "versions missing")
    try:
        expected_hash = str(manifest["manifest_sha256"])
        unsigned = dict(manifest)
        unsigned.pop("manifest_sha256")
        observed_hash = hashlib.sha256(_canonical_json(unsigned)).hexdigest()
        total_frames = int(manifest["total_frames"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ReplayVerificationError(
            ReplayFailureCode.MANIFEST_INVALID, "required metadata missing"
        ) from exc
    if observed_hash != expected_hash or total_frames <= 0:
        raise ReplayVerificationError(ReplayFailureCode.MANIFEST_INVALID, "digest or count mismatch")
    indexes = [int(item.get("segment_index", -1)) for item in manifest["segments"] if isinstance(item, dict)]
    if indexes != list(range(len(manifest["segments"]))):
        raise ReplayVerificationError(ReplayFailureCode.MANIFEST_INVALID, "segment indexes invalid")


def _verify_segment(restored: object, expected: dict[str, object], session_id: str) -> None:
    if (
        restored.session_id != session_id
        or restored.segment_id != expected.get("segment_id")
        or restored.segment_index != int(expected.get("segment_index", -1))
        or restored.ciphertext_sha256 != expected.get("ciphertext_sha256")
        or len(restored.frames) != int(expected.get("frame_count", -1))
        or restored.frames[0].source_index != int(expected.get("first_source_index", -1))
        or restored.frames[-1].source_index != int(expected.get("last_source_index", -1))
    ):
        raise ReplayVerificationError(
            ReplayFailureCode.SEGMENT_INVALID, "manifest and encrypted segment differ"
        )


def _verify_timeline(frames: list[RawFrame], *, expected_total: int) -> None:
    if len(frames) != expected_total or not frames:
        raise ReplayVerificationError(ReplayFailureCode.TIMELINE_INVALID, "frame count mismatch")
    for before, after in zip(frames, frames[1:]):
        if after.source_index <= before.source_index:
            raise ReplayVerificationError(
                ReplayFailureCode.TIMELINE_INVALID, "source indexes are not increasing"
            )
        if after.host_monotonic_ns < before.host_monotonic_ns:
            raise ReplayVerificationError(
                ReplayFailureCode.TIMELINE_INVALID, "host time moves backwards"
            )


def _read_quality_counts(
    session_directory: Path, session_id: str, key_provider: KeyProvider
) -> tuple[int, int]:
    artifacts = tuple(session_directory.glob("derived-*.ffpd"))
    if not artifacts:
        return 0, 0
    if len(artifacts) != 1:
        raise ReplayVerificationError(
            ReplayFailureCode.DERIVED_ARTIFACT_INVALID, "multiple derived observations"
        )
    try:
        derived = read_derived_observation(artifacts[0], key_provider=key_provider)
    except (OSError, DerivedArtifactIntegrityError, ValueError) as exc:
        raise ReplayVerificationError(
            ReplayFailureCode.DERIVED_ARTIFACT_INVALID,
            "derived observation failed authentication or decoding",
        ) from exc
    if derived.get("session_id") != session_id:
        raise ReplayVerificationError(
            ReplayFailureCode.DERIVED_ARTIFACT_INVALID, "derived observation session mismatch"
        )
    processing = derived.get("hardware_processing")
    integrity = processing.get("communication_integrity") if isinstance(processing, dict) else None
    events = integrity.get("events") if isinstance(integrity, dict) else ()
    reconstructed = integrity.get("reconstructed_frame_count", 0) if isinstance(integrity, dict) else 0
    if not isinstance(events, list) or not isinstance(reconstructed, int) or reconstructed < 0:
        raise ReplayVerificationError(
            ReplayFailureCode.DERIVED_ARTIFACT_INVALID, "communication audit invalid"
        )
    return len(events), reconstructed
