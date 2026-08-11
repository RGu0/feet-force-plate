"""Validity-gated promotion from temporary capture data to a local session."""

from __future__ import annotations

import base64
from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import uuid

from client.device.protocol import RawFrame
from client.device.stage_windows import CapturedStageWindow
from client.hardware_standardization.models import PhysicalArraySession
from client.hardware_standardization.public_export import (
    PhysicalPressureSession,
    restore_committed_physical_pressure_session,
)
from client.workflow.protocol import default_standard_protocol
from shared.contracts.client_sync import FormalUploadEnvelope

from .derived_artifact import (
    DerivedArtifact,
    read_derived_observation,
    write_derived_observation,
)
from .segments import (
    ImmutableSegmentWriter,
    SealedSegment,
    _fsync_directory,
    read_segment,
    write_session_manifest,
)
from .stage_attempt import SealedStageAttempt
from .state_store import (
    KeyProvider,
    SensitiveBlobCodec,
    StateStore,
    ValidArtifactRecord,
    ValidSegmentRecord,
)


_STAGE_WINDOW_POLICY_VERSION = "operator-started-stage-window/1"


def _write_atomic_json(path: Path, payload: dict[str, object]) -> None:
    temporary = path.with_suffix(".tmp")
    with temporary.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    _fsync_directory(path.parent)


@dataclass(frozen=True, slots=True)
class CommittedValidSession:
    session_id: str
    total_frames: int
    manifest_sha256: str
    session_directory: Path


class FinalSessionStorageError(RuntimeError):
    """The final stager cannot prove rollback cleanup and must not be retried."""


def read_committed_physical_session(
    root: str | Path,
    *,
    session_id: str,
    store: StateStore,
    key_provider: KeyProvider,
) -> PhysicalPressureSession:
    """Read one locally committed valid session through the public RAY-117 contract."""

    lifecycle, validity, _ended_at_ns = store.session_status(session_id)
    if (lifecycle, validity) != ("CLOSED", "VALID"):
        raise ValueError("local analysis requires a completed valid session")
    artifacts = tuple(
        artifact
        for artifact in store.session_artifacts(session_id)
        if artifact.kind == "HARDWARE_DERIVED_OBSERVATION"
        and artifact.schema_version == "hardware-derived-observation/1"
    )
    if len(artifacts) != 1:
        raise ValueError(
            "local analysis requires exactly one hardware-derived observation"
        )
    observation = read_derived_observation(
        Path(root) / artifacts[0].relative_path,
        key_provider=key_provider,
    )
    if observation.get("session_id") != session_id:
        raise ValueError("derived observation session identity mismatch")
    return restore_committed_physical_pressure_session(
        observation,
        local_session_committed=True,
    )


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
        upload_envelope: FormalUploadEnvelope | None = None,
        segment_duration_seconds: float = 5.0,
        expected_stage_ids: tuple[str, ...] | None = None,
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
        self._upload_envelope = upload_envelope
        self._expected_stage_ids = (
            expected_stage_ids
            if expected_stage_ids is not None
            else tuple(stage.stage_id for stage in default_standard_protocol().stages)
        )
        if not self._expected_stage_ids or any(
            not stage_id for stage_id in self._expected_stage_ids
        ):
            raise ValueError("expected stage ids are required")
        self._writer = ImmutableSegmentWriter(
            self._staging_root,
            session_id=session_id,
            key_provider=key_provider,
            versions=versions,
            segment_duration_seconds=segment_duration_seconds,
        )
        self._sealed: list[SealedSegment] = []
        self._artifacts: list[DerivedArtifact] = []
        self._stage_windows: list[CapturedStageWindow] = []
        self._has_open_frames = False
        self._finished = False
        self._poisoned_reason: str | None = None

    @property
    def staging_directory(self) -> Path:
        return self._staging_root / self._session_id

    @property
    def subject_uuid(self) -> str:
        return self._subject_uuid

    @property
    def upload_envelope(self) -> FormalUploadEnvelope:
        if self._upload_envelope is None:
            raise RuntimeError("formal upload envelope is unavailable")
        return self._upload_envelope

    @property
    def stage_windows(self) -> tuple[CapturedStageWindow, ...]:
        return tuple(self._stage_windows)

    def append(self, frame: RawFrame) -> None:
        self._ensure_active()
        sealed = self._writer.append(frame)
        self._has_open_frames = sealed is None
        if sealed is not None:
            self._sealed.append(sealed)

    def append_verified_stage(
        self,
        attempt: SealedStageAttempt,
        window: CapturedStageWindow,
    ) -> None:
        """Atomically merge one sealed stage in the configured protocol order."""

        self._ensure_active()
        if not isinstance(attempt, SealedStageAttempt) or not (
            attempt._has_verified_provenance()
        ):
            raise TypeError("a sealed stage attempt with verified provenance is required")
        if attempt.session_id != self._session_id:
            raise ValueError(
                "stage attempt session identity does not match the final session"
            )
        if attempt.stage_id != window.stage_id:
            raise ValueError("stage identity must match its captured window")
        if attempt.stage_id in {captured.stage_id for captured in self._stage_windows}:
            raise ValueError("duplicate stage cannot be merged")
        if len(self._stage_windows) >= len(self._expected_stage_ids) or (
            attempt.stage_id != self._expected_stage_ids[len(self._stage_windows)]
        ):
            raise ValueError("stage order does not match the configured protocol")
        if not attempt.frames or len(attempt.frames) != window.frame_count:
            raise ValueError("verified stage frames must match its captured window")

        writer_checkpoint = self._writer.checkpoint()
        sealed_count = len(self._sealed)
        window_count = len(self._stage_windows)
        had_open_frames = self._has_open_frames
        versions = dict(self._versions)
        existing_paths = (
            frozenset(self.staging_directory.iterdir())
            if self.staging_directory.exists()
            else frozenset()
        )
        try:
            policy = self._versions.get("stage_window_policy")
            if policy is None:
                self.freeze_versions(
                    {"stage_window_policy": _STAGE_WINDOW_POLICY_VERSION}
                )
            elif policy != _STAGE_WINDOW_POLICY_VERSION:
                raise ValueError("stage window policy is frozen differently")
            for frame in attempt.frames:
                self.append(frame)
            if self._has_open_frames:
                self._sealed.append(self._writer.close())
                self._has_open_frames = False
            self._stage_windows.append(window)
        except BaseException as merge_failure:
            self._sealed[sealed_count:] = []
            self._stage_windows[window_count:] = []
            self._writer.restore(writer_checkpoint)
            self._has_open_frames = had_open_frames
            self._versions = versions
            try:
                self._remove_transaction_paths(existing_paths)
            except BaseException as cleanup_failure:
                reason = (
                    "final session staging is poisoned after rollback cleanup "
                    f"failed: {type(cleanup_failure).__name__}"
                )
                self._poisoned_reason = reason
                self._finished = True
                error = FinalSessionStorageError(reason)
                error.add_note(
                    f"stage merge first failed with {type(merge_failure).__name__}"
                )
                raise error from cleanup_failure
            raise

    def _remove_transaction_paths(self, existing_paths: frozenset[Path]) -> None:
        """Remove filesystem entries created by one failed stage merge."""

        session_directory = self.staging_directory
        if not session_directory.exists():
            return
        for path in frozenset(session_directory.iterdir()) - existing_paths:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
        if not existing_paths and not any(session_directory.iterdir()):
            session_directory.rmdir()
            if self._staging_root.exists():
                _fsync_directory(self._staging_root)
            return
        _fsync_directory(session_directory)

    def freeze_versions(self, additional_versions: dict[str, str]) -> None:
        """Bind acquisition policies before the first raw frame is accepted."""

        self._ensure_active()
        if self._sealed or self._has_open_frames:
            raise RuntimeError("valid-session versions must be frozen before acquisition")
        self._writer.freeze_versions(additional_versions)
        self._versions.update(additional_versions)

    def append_from_sink(
        self, session_id: str, frame: RawFrame, *, timeout: float | None = None
    ) -> None:
        """DurableFrameSink-compatible adapter; timeout is owned by the caller queue."""

        if session_id != self._session_id:
            raise ValueError("staging sink cannot accept another session id")
        self.append(frame)

    def discard(self, *, reason: str) -> None:
        if self._finished and self._poisoned_reason is None:
            raise RuntimeError("session staging is already finished")
        if not reason:
            raise ValueError("discard reason is required")
        self._finished = True
        if self.staging_directory.exists():
            shutil.rmtree(self.staging_directory)
            _fsync_directory(self._staging_root)

    def staged_frames(self) -> tuple[RawFrame, ...]:
        """Seal any buffered data and return verified temporary frames for gating."""

        self._ensure_active()
        if self._has_open_frames:
            self._sealed.append(self._writer.close())
            self._has_open_frames = False
        if not self._sealed:
            return ()
        frames: list[RawFrame] = []
        for sealed in sorted(self._sealed, key=lambda item: item.segment_index):
            frames.extend(read_segment(sealed.path, self._key_provider).frames)
        return tuple(frames)

    def stage_derived_observation(
        self,
        observation: PhysicalArraySession,
        *,
        processing_metadata: dict[str, object] | None = None,
    ) -> DerivedArtifact:
        """Encrypt a derived observation while the session is still discardable."""

        self._ensure_active()
        if observation.session_id != self._session_id:
            raise ValueError("derived observation must match the staged session id")
        metadata = dict(processing_metadata or {})
        if self._stage_windows:
            metadata["stage_windows"] = [
                {
                    "stage_id": window.stage_id,
                    "start_s": window.start_s,
                    "end_s": window.end_s,
                    "frame_count": window.frame_count,
                }
                for window in self._stage_windows
            ]
        artifact = write_derived_observation(
            self._staging_root,
            session=observation,
            key_provider=self._key_provider,
            processing_metadata=metadata,
        )
        self._artifacts.append(artifact)
        return artifact

    def commit_valid(self, *, ended_at_ns: int) -> CommittedValidSession:
        self._ensure_active()
        self.staged_frames()
        if not self._sealed:
            raise ValueError("cannot commit a session without frames")
        manifest = write_session_manifest(
            self._staging_root,
            session_id=self._session_id,
            segment_paths=[segment.path for segment in self._sealed],
            key_provider=self._key_provider,
            local_quality_outcome="VALID",
            artifacts=[
                {
                    "artifact_id": artifact.artifact_id,
                    "ciphertext_sha256": artifact.ciphertext_sha256,
                    "kind": artifact.kind,
                    "relative_path": artifact.path.name,
                    "schema_version": artifact.schema_version,
                }
                for artifact in self._artifacts
            ],
        )
        records = tuple(
            ValidSegmentRecord(
                segment_id=segment.segment_id,
                relative_path=str((Path("sessions") / self._session_id / segment.path.name)),
                byte_count=segment.byte_count,
                sealed_at_ns=ended_at_ns,
            )
            for segment in self._sealed
        )
        artifact_records = tuple(
            ValidArtifactRecord(
                artifact_id=artifact.artifact_id,
                kind=artifact.kind,
                schema_version=artifact.schema_version,
                relative_path=str(
                    Path("sessions") / self._session_id / artifact.path.name
                ),
                ciphertext_sha256=artifact.ciphertext_sha256,
                byte_count=artifact.byte_count,
            )
            for artifact in self._artifacts
        )
        registration = {
            "registration_version": "ffps-valid-session-registration/1",
            "session_id": self._session_id,
            "subject_uuid": self._subject_uuid,
            "consent_id": self._consent_id,
            "versions_json": json.dumps(self._versions, sort_keys=True),
            "started_at_ns": self._started_at_ns,
            "ended_at_ns": ended_at_ns,
            "manifest_sha256": str(manifest["manifest_sha256"]),
            "upload_envelope": self._encoded_recovery_envelope(),
            "segments": [
                {
                    "segment_id": record.segment_id,
                    "relative_path": record.relative_path,
                    "byte_count": record.byte_count,
                    "sealed_at_ns": record.sealed_at_ns,
                }
                for record in records
            ],
            "artifacts": [
                {
                    "artifact_id": record.artifact_id,
                    "kind": record.kind,
                    "schema_version": record.schema_version,
                    "relative_path": record.relative_path,
                    "ciphertext_sha256": record.ciphertext_sha256,
                    "byte_count": record.byte_count,
                }
                for record in artifact_records
            ],
        }
        _write_atomic_json(self.staging_directory / "registration.json", registration)
        staging = self.staging_directory
        final = self._sessions_root / self._session_id
        if final.exists():
            raise FileExistsError(f"local session already exists: {self._session_id}")
        self._sessions_root.mkdir(parents=True, exist_ok=True)
        os.replace(staging, final)
        _fsync_directory(self._staging_root)
        _fsync_directory(self._sessions_root)
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
                artifacts=artifact_records,
                upload_envelope=self._upload_envelope,
            )
        except Exception:
            os.replace(final, staging)
            _fsync_directory(self._sessions_root)
            _fsync_directory(self._staging_root)
            raise
        (final / "registration.json").unlink()
        _fsync_directory(final)
        self._finished = True
        return CommittedValidSession(
            session_id=self._session_id,
            total_frames=int(manifest["total_frames"]),
            manifest_sha256=str(manifest["manifest_sha256"]),
            session_directory=final,
        )

    def _encoded_recovery_envelope(self) -> str | None:
        if self._upload_envelope is None:
            return None
        plaintext = self._upload_envelope.model_dump_json().encode("utf-8")
        encrypted = SensitiveBlobCodec(self._key_provider).encrypt(
            plaintext,
            context=f"formal_upload_envelope:{self._session_id}",
        )
        return base64.b64encode(encrypted).decode("ascii")

    def _ensure_active(self) -> None:
        if self._poisoned_reason is not None:
            raise FinalSessionStorageError(self._poisoned_reason)
        if self._finished:
            raise RuntimeError("session staging is already finished")

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

    @classmethod
    def recover_promoted_sessions(
        cls, root: str | Path, store: StateStore, key_provider: KeyProvider
    ) -> int:
        """Finish a crash-interrupted post-promotion SQLite registration exactly once."""

        sessions_root = Path(root) / "sessions"
        if not sessions_root.exists():
            return 0
        recovered = 0
        for directory in sessions_root.iterdir():
            registration_path = directory / "registration.json"
            if not directory.is_dir() or not registration_path.is_file():
                continue
            payload = json.loads(registration_path.read_text(encoding="utf-8"))
            if payload.get("registration_version") != "ffps-valid-session-registration/1":
                raise ValueError("unsupported valid-session registration recovery record")
            session_id = str(payload["session_id"])
            if directory.name != session_id:
                raise ValueError("registration session id does not match directory")
            try:
                store.session_status(session_id)
            except KeyError:
                segments = tuple(
                    ValidSegmentRecord(
                        segment_id=str(item["segment_id"]),
                        relative_path=str(item["relative_path"]),
                        byte_count=int(item["byte_count"]),
                        sealed_at_ns=int(item["sealed_at_ns"]),
                    )
                    for item in payload["segments"]
                )
                artifacts = tuple(
                    ValidArtifactRecord(
                        artifact_id=str(item["artifact_id"]),
                        kind=str(item["kind"]),
                        schema_version=str(item["schema_version"]),
                        relative_path=str(item["relative_path"]),
                        ciphertext_sha256=str(item["ciphertext_sha256"]),
                        byte_count=int(item["byte_count"]),
                    )
                    for item in payload["artifacts"]
                )
                for record in segments:
                    restored = read_segment(Path(root) / record.relative_path, key_provider)
                    if restored.session_id != session_id or restored.segment_id != record.segment_id:
                        raise ValueError("promoted raw segment identity mismatch")
                for record in artifacts:
                    derived = read_derived_observation(
                        Path(root) / record.relative_path, key_provider=key_provider
                    )
                    if derived.get("session_id") != session_id:
                        raise ValueError("promoted derived artifact session mismatch")
                encoded_envelope = payload.get("upload_envelope")
                upload_envelope = None
                if encoded_envelope is not None:
                    if not isinstance(encoded_envelope, str):
                        raise ValueError("invalid formal upload recovery envelope")
                    try:
                        encrypted_envelope = base64.b64decode(
                            encoded_envelope.encode("ascii"), validate=True
                        )
                        plaintext_envelope = SensitiveBlobCodec(key_provider).decrypt(
                            encrypted_envelope,
                            context=f"formal_upload_envelope:{session_id}",
                        )
                        upload_envelope = FormalUploadEnvelope.model_validate_json(
                            plaintext_envelope
                        )
                    except Exception as exc:
                        raise ValueError(
                            "invalid formal upload recovery envelope"
                        ) from exc
                store.commit_valid_session(
                    session_id,
                    subject_uuid=str(payload["subject_uuid"]),
                    consent_id=payload["consent_id"],
                    versions_json=str(payload["versions_json"]).encode("utf-8"),
                    started_at_ns=int(payload["started_at_ns"]),
                    ended_at_ns=int(payload["ended_at_ns"]),
                    manifest_sha256=str(payload["manifest_sha256"]),
                    segments=segments,
                    artifacts=artifacts,
                    upload_envelope=upload_envelope,
                )
                recovered += 1
            registration_path.unlink()
            _fsync_directory(directory)
        return recovered


class StagedFrameSink:
    """Acquisition-facing adapter that owns one temporary valid-session stager."""

    def __init__(self, stager: ValidSessionStager) -> None:
        self._stager = stager

    def append(
        self, session_id: str, frame: RawFrame, *, timeout: float | None = None
    ) -> None:
        self._stager.append_from_sink(session_id, frame, timeout=timeout)

    def discard(self, *, reason: str) -> None:
        self._stager.discard(reason=reason)


def delete_completed_valid_session(
    root: str | Path, *, session_id: str, store: StateStore
) -> None:
    """Operator-only single-session deletion with a reversible index-failure window."""

    root_path = Path(root)
    sessions_root = root_path / "sessions"
    session_directory = sessions_root / session_id
    if not session_directory.is_dir():
        raise FileNotFoundError(session_directory)
    deleting_root = root_path / ".deleting"
    deleting_root.mkdir(parents=True, exist_ok=True)
    pending = deleting_root / f"{session_id}-{uuid.uuid4()}"
    os.replace(session_directory, pending)
    _fsync_directory(sessions_root)
    _fsync_directory(deleting_root)
    try:
        store.delete_completed_valid_session(session_id)
    except Exception:
        os.replace(pending, session_directory)
        _fsync_directory(deleting_root)
        _fsync_directory(sessions_root)
        raise
    try:
        shutil.rmtree(pending)
        _fsync_directory(deleting_root)
    except Exception as exc:
        raise RuntimeError(
            "database index removed but manual-deletion files require recovery"
        ) from exc
