"""Strict, local-only support events with a verifiable rotating audit trail."""

from __future__ import annotations

import errno
import hashlib
import json
import os
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from pydantic import Field, field_validator

from shared.contracts.client_sync import canonical_json_bytes
from shared.contracts.cloud import ContractModel, Sha256Hex
from shared.contracts.validation_telemetry import ErrorCode, TechnicalIdentifier


MAX_GENERATION_BYTES = 2 * 1024 * 1024
_ACTIVE_FILENAME = "events.jsonl"
_LOCK_FILENAME = ".events.lock"
_GENERATION_FILENAMES = ("events.2.jsonl", "events.1.jsonl", _ACTIVE_FILENAME)


class SafeClientEventName(StrEnum):
    APPLICATION_STARTED = "APPLICATION_STARTED"
    APPLICATION_EXITED = "APPLICATION_EXITED"
    AUTH_ACTIVATION_ACCEPTED = "AUTH_ACTIVATION_ACCEPTED"
    AUTH_ACTIVATION_REJECTED = "AUTH_ACTIVATION_REJECTED"
    AUTH_LOGIN_ACCEPTED = "AUTH_LOGIN_ACCEPTED"
    AUTH_LOGIN_REJECTED = "AUTH_LOGIN_REJECTED"
    AUTH_REFRESH_ACCEPTED = "AUTH_REFRESH_ACCEPTED"
    AUTH_REFRESH_REJECTED = "AUTH_REFRESH_REJECTED"
    UPGRADE_APPLIED = "UPGRADE_APPLIED"
    UPGRADE_ROLLED_BACK = "UPGRADE_ROLLED_BACK"
    DIAGNOSTIC_EXPORT_COMPLETED = "DIAGNOSTIC_EXPORT_COMPLETED"
    DIAGNOSTIC_EXPORT_FAILED = "DIAGNOSTIC_EXPORT_FAILED"


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
    """A local, private, three-generation append-only event store."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self._root, 0o700)
        with self._exclusive_process_lock():
            self._recover_incomplete_final_line()

    def append(self, event: SafeClientEvent) -> None:
        with self._exclusive_process_lock():
            records = self._verified_records_unlocked()
            previous_sha256 = records[-1].sha256 if records else None
            record = SafeClientLogRecord(
                event=event,
                previous_sha256=previous_sha256,
                sha256=_record_digest(event, previous_sha256),
            )
            encoded = canonical_json_bytes(record) + b"\n"
            active_path = self._active_path
            prefix = b""
            if active_path.exists() and active_path.stat().st_size:
                with active_path.open("rb") as handle:
                    handle.seek(-1, os.SEEK_END)
                    if handle.read(1) != b"\n":
                        prefix = b"\n"
            current_size = active_path.stat().st_size if active_path.exists() else 0
            if current_size and current_size + len(prefix) + len(encoded) > MAX_GENERATION_BYTES:
                self._rotate()
                prefix = b""
            self._append_bytes(self._active_path, prefix + encoded)

    def verified_records(self) -> tuple[SafeClientLogRecord, ...]:
        with self._exclusive_process_lock():
            return self._verified_records_unlocked()

    def _verified_records_unlocked(self) -> tuple[SafeClientLogRecord, ...]:
        records: list[SafeClientLogRecord] = []
        previous_sha256: str | None = None
        for path in self._generation_paths():
            for line_number, raw_line in enumerate(path.read_bytes().splitlines(), start=1):
                if not raw_line:
                    raise ValueError(f"empty safe event record at {path}:{line_number}")
                try:
                    record = SafeClientLogRecord.model_validate_json(raw_line)
                except (ValueError, json.JSONDecodeError) as exc:
                    raise ValueError(f"invalid safe event record at {path}:{line_number}") from exc
                if previous_sha256 is not None and record.previous_sha256 != previous_sha256:
                    raise ValueError(f"broken safe event chain at {path}:{line_number}")
                if record.sha256 != _record_digest(record.event, record.previous_sha256):
                    raise ValueError(f"invalid safe event digest at {path}:{line_number}")
                records.append(record)
                previous_sha256 = record.sha256
        return tuple(records)

    @property
    def _active_path(self) -> Path:
        return self._root / _ACTIVE_FILENAME

    @property
    def _lock_path(self) -> Path:
        return self._root / _LOCK_FILENAME

    def _generation_paths(self) -> tuple[Path, ...]:
        return tuple(
            self._root / filename
            for filename in _GENERATION_FILENAMES
            if (self._root / filename).exists()
        )

    def _recover_incomplete_final_line(self) -> None:
        path = self._active_path
        if not path.exists() or not path.stat().st_size:
            return
        data = path.read_bytes()
        if data.endswith(b"\n"):
            return
        line_start = data.rfind(b"\n") + 1
        try:
            json.loads(data[line_start:].decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._write_bytes(path, data[:line_start])

    @contextmanager
    def _exclusive_process_lock(self) -> Iterator[None]:
        """Serialize complete-chain reads and writes across client processes."""
        descriptor = os.open(self._lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            _set_private_file_mode(self._lock_path, descriptor)
            with os.fdopen(descriptor, "r+b", closefd=False) as handle:
                if os.name == "nt":
                    handle.seek(0, os.SEEK_END)
                    if handle.tell() == 0:
                        handle.write(b"\0")
                        handle.flush()
                    handle.seek(0)
                    unlock = _acquire_windows_lock(handle.fileno())
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                    unlock = lambda: fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                try:
                    yield
                finally:
                    unlock()
        finally:
            os.close(descriptor)

    def _rotate(self) -> None:
        oldest = self._root / _GENERATION_FILENAMES[0]
        oldest.unlink(missing_ok=True)
        for source_name, target_name in (
            ("events.1.jsonl", "events.2.jsonl"),
            (_ACTIVE_FILENAME, "events.1.jsonl"),
        ):
            source = self._root / source_name
            if source.exists():
                os.replace(source, self._root / target_name)

    @staticmethod
    def _append_bytes(path: Path, data: bytes) -> None:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            _set_private_file_mode(path, descriptor)
            with os.fdopen(descriptor, "ab", closefd=False) as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
        finally:
            os.close(descriptor)

    @staticmethod
    def _write_bytes(path: Path, data: bytes) -> None:
        descriptor = os.open(path, os.O_WRONLY | os.O_TRUNC, 0o600)
        try:
            _set_private_file_mode(path, descriptor)
            with os.fdopen(descriptor, "wb", closefd=False) as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
        finally:
            os.close(descriptor)


def _set_private_file_mode(path: Path, descriptor: int) -> None:
    """Apply private permissions on POSIX and Windows Python versions."""
    try:
        os.fchmod(descriptor, 0o600)
    except AttributeError:
        os.chmod(path, 0o600)


def _acquire_windows_lock(descriptor: int) -> Callable[[], None]:
    """Wait through transient Windows sharing contention without dropping an event."""
    import msvcrt

    locking = getattr(msvcrt, "locking")
    nonblocking_lock = getattr(msvcrt, "LK_NBLCK")
    unlock_code = getattr(msvcrt, "LK_UNLCK")
    while True:
        try:
            locking(descriptor, nonblocking_lock, 1)
            break
        except OSError as exc:
            if exc.errno not in {errno.EACCES, errno.EAGAIN}:
                raise
            time.sleep(0.05)
    return lambda: locking(descriptor, unlock_code, 1)


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


def _record_digest(event: SafeClientEvent, previous_sha256: str | None) -> str:
    previous_digest_bytes = bytes.fromhex(previous_sha256) if previous_sha256 else b""
    return hashlib.sha256(canonical_json_bytes(event) + previous_digest_bytes).hexdigest()
