"""Strict, local-only support events with a verifiable rotating audit trail."""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from pydantic import Field, field_validator
from techflex_cloud_foundation import ChainedAppendLog
from techflex_cloud_foundation.durability import atomic_write, fsync_directory

from client.support.legacy_safe_event_chain import (
    LEGACY_DIRECTORY_NAME,
    legacy_chain_files,
    verify_legacy_chain,
)
from techflex_cloud_foundation.contracts.cloud import ContractModel, Sha256Hex
from techflex_cloud_foundation.contracts.validation_telemetry import ErrorCode, TechnicalIdentifier


MAX_GENERATION_BYTES = 2 * 1024 * 1024


class SafeClientEventName(StrEnum):
    APPLICATION_STARTED = "APPLICATION_STARTED"
    APPLICATION_EXITED = "APPLICATION_EXITED"
    AUTH_ACTIVATION_ACCEPTED = "AUTH_ACTIVATION_ACCEPTED"
    AUTH_ACTIVATION_REJECTED = "AUTH_ACTIVATION_REJECTED"
    AUTH_LOGIN_ACCEPTED = "AUTH_LOGIN_ACCEPTED"
    AUTH_LOGIN_REJECTED = "AUTH_LOGIN_REJECTED"
    AUTH_REFRESH_ACCEPTED = "AUTH_REFRESH_ACCEPTED"
    AUTH_REFRESH_REJECTED = "AUTH_REFRESH_REJECTED"
    LIVE_CAPTURE_FAILED = "LIVE_CAPTURE_FAILED"
    LIVE_CAPTURE_CONNECTION_FAILED = "LIVE_CAPTURE_CONNECTION_FAILED"
    LIVE_CAPTURE_INITIALIZATION_FAILED = "LIVE_CAPTURE_INITIALIZATION_FAILED"
    LIVE_CAPTURE_METADATA_FAILED = "LIVE_CAPTURE_METADATA_FAILED"
    LIVE_CAPTURE_LOCAL_IDENTITY_FAILED = "LIVE_CAPTURE_LOCAL_IDENTITY_FAILED"
    LIVE_CAPTURE_FORMAL_ENVELOPE_FAILED = "LIVE_CAPTURE_FORMAL_ENVELOPE_FAILED"
    LIVE_CAPTURE_FORMAL_ENVELOPE_LOCAL_RECORD_MISSING = "LIVE_CAPTURE_FORMAL_ENVELOPE_LOCAL_RECORD_MISSING"
    LIVE_CAPTURE_FORMAL_ENVELOPE_CONTRACT_VALUE_INVALID = "LIVE_CAPTURE_FORMAL_ENVELOPE_CONTRACT_VALUE_INVALID"
    LIVE_CAPTURE_FORMAL_ENVELOPE_CONTRACT_TYPE_INVALID = "LIVE_CAPTURE_FORMAL_ENVELOPE_CONTRACT_TYPE_INVALID"
    LIVE_CAPTURE_FORMAL_ENVELOPE_UNEXPECTED = "LIVE_CAPTURE_FORMAL_ENVELOPE_UNEXPECTED"
    LIVE_CAPTURE_SESSION_STAGER_FAILED = "LIVE_CAPTURE_SESSION_STAGER_FAILED"
    LIVE_CAPTURE_STREAM_FAILED = "LIVE_CAPTURE_STREAM_FAILED"
    LIVE_CAPTURE_TRANSPORT_DISCONNECTED = "LIVE_CAPTURE_TRANSPORT_DISCONNECTED"
    LIVE_CAPTURE_SIGNAL_TIMEOUT = "LIVE_CAPTURE_SIGNAL_TIMEOUT"
    LIVE_CAPTURE_DECODE_FAILED = "LIVE_CAPTURE_DECODE_FAILED"
    LIVE_CAPTURE_GATE_FAILED = "LIVE_CAPTURE_GATE_FAILED"
    LIVE_CAPTURE_DISPLAY_HANDOFF_FAILED = "LIVE_CAPTURE_DISPLAY_HANDOFF_FAILED"
    LIVE_CAPTURE_STAGE_STORAGE_FAILED = "LIVE_CAPTURE_STAGE_STORAGE_FAILED"
    UPGRADE_APPLIED = "UPGRADE_APPLIED"
    UPGRADE_ROLLED_BACK = "UPGRADE_ROLLED_BACK"
    DIAGNOSTIC_EXPORT_COMPLETED = "DIAGNOSTIC_EXPORT_COMPLETED"
    DIAGNOSTIC_EXPORT_FAILED = "DIAGNOSTIC_EXPORT_FAILED"
    REPORT_GENERATION_FAILED = "REPORT_GENERATION_FAILED"


class SafeClientEventOutcome(StrEnum):
    OK = "OK"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


class SafeClientCounters(ContractModel):
    attempt_count: int | None = Field(default=None, ge=0, le=1_000_000)
    pending_event_count: int | None = Field(default=None, ge=0, le=1_000_000)
    duration_ms: int | None = Field(default=None, ge=0, le=86_400_000)


class SafeClientEvent(ContractModel):
    schema_version: Literal["safe-client-event/1"] = "safe-client-event/1"
    event_id: UUID
    occurred_at: datetime
    name: SafeClientEventName
    outcome: SafeClientEventOutcome
    error_code: ErrorCode | None = None
    client_installation_id: UUID
    app_version: TechnicalIdentifier
    protocol_version: TechnicalIdentifier
    data_mode_version: TechnicalIdentifier
    config_version: TechnicalIdentifier
    counters: SafeClientCounters = Field(default_factory=SafeClientCounters)

    @field_validator("occurred_at")
    @classmethod
    def require_utc_datetime(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("occurred_at must use UTC")
        return value.astimezone(UTC)


class SafeClientLogRecord(ContractModel):
    schema_version: Literal["safe-client-log-record/1"] = "safe-client-log-record/1"
    event: SafeClientEvent
    previous_sha256: Sha256Hex | None = None
    sha256: Sha256Hex


class SafeClientEventStore:
    """A local, private, three-generation append-only event store.

    The hash chain, rotation, fsync, owner-only permissions, cross-process lock
    and crash recovery are foundation's ``ChainedAppendLog``; this class keeps
    the typed event contract on top of it.  A log written before the move to
    foundation is archived once, see :mod:`client.support.legacy_safe_event_chain`.
    """

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self._root, 0o700)
        archived = _archive_legacy_chain(self._root)
        self._log = ChainedAppendLog(
            self._root, max_generation_bytes=MAX_GENERATION_BYTES, generations=3
        )
        if _legacy_anchor_pending(self._root):
            if archived or not _chain_has_anchor(self._log):
                self._log.append(_legacy_anchor_payload(self._root))
            _mark_legacy_anchored(self._root)

    def append(self, event: SafeClientEvent) -> None:
        self._log.append(event.model_dump(mode="json"))

    def verified_records(self) -> tuple[SafeClientLogRecord, ...]:
        """Every surviving event with its chain digests; anchors are not events."""

        return tuple(
            SafeClientLogRecord(
                event=SafeClientEvent.model_validate(record.payload),
                previous_sha256=record.previous_sha256,
                sha256=record.sha256,
            )
            for record in self._log.verified_records()
            if record.payload.get("schema_version") == _EVENT_SCHEMA
        )

    def anchors(self) -> tuple[dict[str, object], ...]:
        """Records that mark a chain restart (an archived pre-foundation log)."""

        return tuple(
            dict(record.payload)
            for record in self._log.verified_records()
            if record.payload.get("schema_version") == _ANCHOR_SCHEMA
        )


_EVENT_SCHEMA = "safe-client-event/1"
_ANCHOR_SCHEMA = "safe-client-log-anchor/1"
_ANCHORED_MARKER = ".anchored"


def _archive_legacy_chain(root: Path) -> bool:
    """Move an old-format log into ``legacy/`` unchanged; True when files moved.

    Tolerates a second process doing the same move at the same moment (a source
    that is already gone is skipped) and fails closed instead of overwriting:
    a file still in ``root`` whose name is already taken in ``legacy/`` means
    two generations of the same log.  Directory entries are made durable
    before the anchor is written.
    """

    old_files = legacy_chain_files(root)
    if not old_files:
        return False
    archive = root / LEGACY_DIRECTORY_NAME
    archive.mkdir(exist_ok=True, mode=0o700)
    fsync_directory(root)
    moved = False
    for path in old_files:
        target = archive / path.name
        if target.exists():
            if not path.exists():
                continue  # the other process finished this move between our two checks
            raise RuntimeError(
                f"legacy safe-event archive already holds {path.name}; refusing to overwrite"
            )
        try:
            os.replace(path, target)
        except FileNotFoundError:
            continue
        moved = True
    fsync_directory(archive)
    fsync_directory(root)
    return moved


def _legacy_anchor_pending(root: Path) -> bool:
    """An archive exists and its anchor has not been confirmed by the marker."""

    archive = root / LEGACY_DIRECTORY_NAME
    if not archive.is_dir() or (archive / _ANCHORED_MARKER).exists():
        return False
    return any(entry.name != _ANCHORED_MARKER for entry in archive.iterdir())


def _chain_has_anchor(log: ChainedAppendLog) -> bool:
    """Whether the new chain already holds the anchor (a stop before the marker).

    A chain that cannot be read is not opened here: reading reports it, and
    chaining another record onto it would only bury the fault.
    """

    try:
        return any(
            record.payload.get("schema_version") == _ANCHOR_SCHEMA
            for record in log.verified_records()
        )
    except ValueError:
        return True


def _mark_legacy_anchored(root: Path) -> None:
    """Record, outside the rotating chain, that the anchor was written.

    Staged under a name no other process shares: two simultaneous first starts
    both get here, and a fixed staging name let one rename the other's file away.
    """

    atomic_write(root / LEGACY_DIRECTORY_NAME / _ANCHORED_MARKER, b"anchored\n")


def _legacy_anchor_payload(root: Path) -> dict[str, object]:
    summary = verify_legacy_chain(root / LEGACY_DIRECTORY_NAME)
    return {
        "schema_version": _ANCHOR_SCHEMA,
        "kind": "LEGACY_CHAIN_ARCHIVED",
        "archived_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "legacy_directory": LEGACY_DIRECTORY_NAME,
        "legacy_files": list(summary.file_names),
        "legacy_verified": summary.verified,
        "legacy_failure": summary.failure,
        "legacy_record_count": summary.record_count,
        "legacy_first_sha256": summary.first_sha256,
        "legacy_head_sha256": summary.head_sha256,
        "legacy_truncated_tail": summary.truncated_tail,
    }


class SafeClientEventRecorder:
    """The sole producer API for privacy-safe client support events."""

    def __init__(
        self,
        store: SafeClientEventStore,
        *,
        client_installation_id: UUID,
        app_version: TechnicalIdentifier,
        protocol_version: TechnicalIdentifier,
        data_mode_version: TechnicalIdentifier,
        config_version: TechnicalIdentifier,
        event_id_factory: Callable[[], UUID] = uuid4,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._store = store
        self._client_installation_id = client_installation_id
        self._app_version = app_version
        self._protocol_version = protocol_version
        self._data_mode_version = data_mode_version
        self._config_version = config_version
        self._event_id_factory = event_id_factory
        self._now = now

    def record(
        self,
        name: SafeClientEventName,
        outcome: SafeClientEventOutcome,
        *,
        error_code: ErrorCode | None = None,
        counters: SafeClientCounters | None = None,
    ) -> bool:
        event = SafeClientEvent(
            event_id=self._event_id_factory(),
            occurred_at=self._now(),
            name=name,
            outcome=outcome,
            error_code=error_code,
            client_installation_id=self._client_installation_id,
            app_version=self._app_version,
            protocol_version=self._protocol_version,
            data_mode_version=self._data_mode_version,
            config_version=self._config_version,
            counters=counters or SafeClientCounters(),
        )
        try:
            self._store.append(event)
        except Exception:
            return False
        return True
