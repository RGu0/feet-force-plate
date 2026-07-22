"""SQLite state boundary for local sessions, quotas, recovery, and cleanup."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import os
from pathlib import Path
import sqlite3
import threading
from typing import Protocol

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


SCHEMA_VERSION = 2
OFFLINE_LIMIT_NS = 24 * 60 * 60 * 1_000_000_000
PENDING_SESSION_LIMIT = 50
PENDING_BYTE_LIMIT = 2 * 1024 * 1024 * 1024


class KeyProvider(Protocol):
    """Key handle boundary implemented by an OS secure-storage adapter."""

    def get_key(self) -> bytes: ...


class SensitiveBlobCodec:
    """AES-256-GCM envelope whose key is fetched, never persisted in SQLite."""

    def __init__(self, key_provider: KeyProvider) -> None:
        self._key_provider = key_provider

    def encrypt(self, plaintext: bytes, *, context: str) -> bytes:
        key = self._key_provider.get_key()
        if len(key) != 32:
            raise ValueError("OS key provider must return a 32-byte AES-256 key")
        nonce = os.urandom(12)
        ciphertext = AESGCM(key).encrypt(nonce, plaintext, context.encode("utf-8"))
        return b"\x01" + nonce + ciphertext

    def decrypt(self, envelope: bytes, *, context: str) -> bytes:
        if len(envelope) < 30 or envelope[0] != 1:
            raise ValueError("unsupported or truncated sensitive blob envelope")
        key = self._key_provider.get_key()
        if len(key) != 32:
            raise ValueError("OS key provider must return a 32-byte AES-256 key")
        return AESGCM(key).decrypt(
            envelope[1:13], envelope[13:], context.encode("utf-8")
        )


class GateReason(StrEnum):
    OFFLINE_TOO_LONG = "OFFLINE_TOO_LONG"
    PENDING_SESSION_LIMIT = "PENDING_SESSION_LIMIT"
    PENDING_BYTE_LIMIT = "PENDING_BYTE_LIMIT"
    INSUFFICIENT_DISK = "INSUFFICIENT_DISK"


@dataclass(frozen=True, slots=True)
class OfflineSnapshot:
    last_successful_online_ns: int | None
    pending_session_count: int
    pending_bytes: int


@dataclass(frozen=True, slots=True)
class NewTestDecision:
    allow_new_test: bool
    reasons: tuple[GateReason, ...]
    allow_current_test_finalize: bool = True
    allow_existing_report_view: bool = True
    allow_upload: bool = True


@dataclass(frozen=True, slots=True)
class RecoveryResult:
    sessions_marked_incomplete: int
    uploads_requeued: int
    telemetry_requeued: int = 0


@dataclass(frozen=True, slots=True)
class CleanupCandidate:
    segment_id: str
    relative_path: str
    byte_count: int


@dataclass(frozen=True, slots=True)
class TelemetryEvent:
    event_id: str
    event_type: str
    schema_version: str
    payload_json: bytes
    state: str
    attempt_count: int
    created_at_ns: int


@dataclass(frozen=True, slots=True)
class StoredValidationResult:
    validation_run_id: str
    outcome: str
    reason: str | None


_MIGRATION_1 = """
CREATE TABLE IF NOT EXISTS subject_refs (
    subject_uuid TEXT PRIMARY KEY,
    encrypted_ref BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS consent_records (
    consent_id TEXT PRIMARY KEY,
    subject_uuid TEXT NOT NULL REFERENCES subject_refs(subject_uuid),
    encrypted_payload BLOB NOT NULL,
    recorded_at_ns INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    subject_uuid TEXT NOT NULL REFERENCES subject_refs(subject_uuid),
    consent_id TEXT REFERENCES consent_records(consent_id),
    lifecycle_status TEXT NOT NULL,
    validity_status TEXT NOT NULL DEFAULT 'UNKNOWN',
    started_at_ns INTEGER NOT NULL,
    ended_at_ns INTEGER,
    versions_json BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS segments (
    segment_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    relative_path TEXT NOT NULL UNIQUE,
    byte_count INTEGER NOT NULL CHECK (byte_count >= 0),
    state TEXT NOT NULL,
    sealed_at_ns INTEGER NOT NULL,
    acknowledged_at_ns INTEGER,
    retain_until_ns INTEGER
);
CREATE TABLE IF NOT EXISTS upload_tasks (
    upload_task_id TEXT PRIMARY KEY,
    segment_id TEXT NOT NULL REFERENCES segments(segment_id) ON DELETE CASCADE,
    state TEXT NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS report_versions (
    report_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    state TEXT NOT NULL,
    relative_path TEXT,
    PRIMARY KEY (report_id, version)
);
CREATE TABLE IF NOT EXISTS terminal_state (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    last_successful_online_ns INTEGER
);
INSERT OR IGNORE INTO terminal_state(singleton, last_successful_online_ns)
VALUES (1, NULL);
CREATE INDEX IF NOT EXISTS idx_segments_pending ON segments(state, session_id);
CREATE INDEX IF NOT EXISTS idx_segments_cleanup ON segments(state, retain_until_ns);
"""


_MIGRATION_2 = """
CREATE TABLE IF NOT EXISTS device_validation_runs (
    validation_run_id TEXT PRIMARY KEY,
    previous_validation_run_id TEXT,
    terminal_id TEXT NOT NULL,
    device_ref TEXT NOT NULL,
    attempt_number INTEGER NOT NULL CHECK (attempt_number > 0),
    outcome TEXT NOT NULL,
    reason TEXT,
    error_code TEXT,
    diagnostic_id TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    payload_json BLOB NOT NULL,
    started_at_ns INTEGER NOT NULL,
    completed_at_ns INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS telemetry_events (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    payload_json BLOB NOT NULL,
    state TEXT NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    created_at_ns INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_validation_device_history
ON device_validation_runs(device_ref, completed_at_ns DESC, attempt_number DESC);
CREATE INDEX IF NOT EXISTS idx_telemetry_pending
ON telemetry_events(state, created_at_ns, event_id);
"""


class StateStore:
    """Thread-safe SQLite repository with explicit transaction boundaries."""

    def __init__(self, path: str | Path, codec: SensitiveBlobCodec) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._codec = codec
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA synchronous=FULL")
        self._connection.execute("PRAGMA busy_timeout=5000")
        self._migrate()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    @property
    def journal_mode(self) -> str:
        with self._lock:
            row = self._connection.execute("PRAGMA journal_mode").fetchone()
            return str(row[0]).lower()

    @property
    def synchronous_level(self) -> int:
        """SQLite durability level; FULL is required for sealed-segment state."""

        with self._lock:
            row = self._connection.execute("PRAGMA synchronous").fetchone()
            return int(row[0])

    @property
    def busy_timeout_ms(self) -> int:
        """Bounded writer contention timeout used by the local state boundary."""

        with self._lock:
            row = self._connection.execute("PRAGMA busy_timeout").fetchone()
            return int(row[0])

    @property
    def schema_version(self) -> int:
        with self._lock:
            row = self._connection.execute("PRAGMA user_version").fetchone()
            return int(row[0])

    def table_names(self) -> set[str]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            return {str(row[0]) for row in rows}

    def _migrate(self) -> None:
        with self._lock, self._connection:
            version = int(self._connection.execute("PRAGMA user_version").fetchone()[0])
            if version > SCHEMA_VERSION:
                raise RuntimeError(
                    f"database schema {version} is newer than supported {SCHEMA_VERSION}"
                )
            if version < 1:
                self._connection.executescript(_MIGRATION_1)
                self._connection.execute("PRAGMA user_version=1")
            if version < 2:
                self._connection.executescript(_MIGRATION_2)
                self._connection.execute("PRAGMA user_version=2")

    def record_validation_audit(
        self,
        *,
        validation_run_id: str,
        previous_validation_run_id: str | None,
        terminal_id: str,
        device_ref: str,
        attempt_number: int,
        outcome: str,
        reason: str | None,
        error_code: str | None,
        diagnostic_id: str,
        schema_version: str,
        payload_json: bytes,
        started_at_ns: int,
        completed_at_ns: int,
        telemetry_event_id: str,
        telemetry_schema_version: str,
        created_at_ns: int,
    ) -> None:
        """Atomically persist a safe run summary and queue its telemetry event."""

        with self._lock, self._connection:
            self._connection.execute(
                """INSERT INTO device_validation_runs(
                    validation_run_id, previous_validation_run_id, terminal_id,
                    device_ref, attempt_number, outcome, reason, error_code,
                    diagnostic_id, schema_version, payload_json, started_at_ns,
                    completed_at_ns
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    validation_run_id,
                    previous_validation_run_id,
                    terminal_id,
                    device_ref,
                    attempt_number,
                    outcome,
                    reason,
                    error_code,
                    diagnostic_id,
                    schema_version,
                    payload_json,
                    started_at_ns,
                    completed_at_ns,
                ),
            )
            self._connection.execute(
                """INSERT INTO telemetry_events(
                    event_id, event_type, schema_version, payload_json, state,
                    attempt_count, created_at_ns
                ) VALUES (?, 'DEVICE_VALIDATION_RUN', ?, ?, 'PENDING', 0, ?)""",
                (
                    telemetry_event_id,
                    telemetry_schema_version,
                    payload_json,
                    created_at_ns,
                ),
            )

    def validation_run_payload(self, validation_run_id: str) -> bytes:
        with self._lock:
            row = self._connection.execute(
                """SELECT payload_json FROM device_validation_runs
                WHERE validation_run_id=?""",
                (validation_run_id,),
            ).fetchone()
        if row is None:
            raise KeyError(validation_run_id)
        return bytes(row[0])

    def recent_validation_results(
        self,
        device_ref: str,
        *,
        limit: int,
    ) -> list[StoredValidationResult]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        with self._lock:
            rows = self._connection.execute(
                """SELECT validation_run_id, outcome, reason
                FROM device_validation_runs WHERE device_ref=?
                ORDER BY completed_at_ns DESC, attempt_number DESC
                LIMIT ?""",
                (device_ref, limit),
            ).fetchall()
        return [
            StoredValidationResult(str(row[0]), str(row[1]), row[2])
            for row in rows
        ]

    def pending_telemetry_events(self, *, limit: int) -> list[TelemetryEvent]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        with self._lock:
            rows = self._connection.execute(
                """SELECT event_id, event_type, schema_version, payload_json,
                    state, attempt_count, created_at_ns
                FROM telemetry_events WHERE state='PENDING'
                ORDER BY created_at_ns, event_id LIMIT ?""",
                (limit,),
            ).fetchall()
        return [
            TelemetryEvent(
                event_id=str(row[0]),
                event_type=str(row[1]),
                schema_version=str(row[2]),
                payload_json=bytes(row[3]),
                state=str(row[4]),
                attempt_count=int(row[5]),
                created_at_ns=int(row[6]),
            )
            for row in rows
        ]

    def set_telemetry_event_state(
        self,
        event_id: str,
        *,
        state: str,
        increment_attempt: bool = False,
    ) -> None:
        allowed_states = {"PENDING", "UPLOADING", "ACKNOWLEDGED", "QUARANTINED"}
        if state not in allowed_states:
            raise ValueError("unsupported telemetry state")
        increment = 1 if increment_attempt else 0
        with self._lock, self._connection:
            updated = self._connection.execute(
                """UPDATE telemetry_events SET state=?, attempt_count=attempt_count+?
                WHERE event_id=?""",
                (state, increment, event_id),
            ).rowcount
        if not updated:
            raise KeyError(event_id)

    def put_subject_ref(self, subject_uuid: str, plaintext: bytes) -> None:
        encrypted = self._codec.encrypt(
            plaintext, context=f"subject_ref:{subject_uuid}"
        )
        with self._lock, self._connection:
            self._connection.execute(
                """INSERT INTO subject_refs(subject_uuid, encrypted_ref) VALUES (?, ?)
                ON CONFLICT(subject_uuid) DO UPDATE
                SET encrypted_ref=excluded.encrypted_ref""",
                (subject_uuid, encrypted),
            )

    def get_subject_ref(self, subject_uuid: str) -> bytes:
        with self._lock:
            row = self._connection.execute(
                "SELECT encrypted_ref FROM subject_refs WHERE subject_uuid=?",
                (subject_uuid,),
            ).fetchone()
        if row is None:
            raise KeyError(subject_uuid)
        return self._codec.decrypt(
            bytes(row[0]), context=f"subject_ref:{subject_uuid}"
        )

    def put_consent_record(
        self,
        consent_id: str,
        subject_uuid: str,
        plaintext: bytes,
        *,
        recorded_at_ns: int,
    ) -> None:
        encrypted = self._codec.encrypt(
            plaintext, context=f"consent_record:{consent_id}"
        )
        with self._lock, self._connection:
            self._connection.execute(
                """INSERT INTO consent_records(
                    consent_id, subject_uuid, encrypted_payload, recorded_at_ns
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(consent_id) DO UPDATE SET
                    subject_uuid=excluded.subject_uuid,
                    encrypted_payload=excluded.encrypted_payload,
                    recorded_at_ns=excluded.recorded_at_ns""",
                (consent_id, subject_uuid, encrypted, recorded_at_ns),
            )

    def get_consent_record(self, consent_id: str) -> bytes:
        with self._lock:
            row = self._connection.execute(
                "SELECT encrypted_payload FROM consent_records WHERE consent_id=?",
                (consent_id,),
            ).fetchone()
        if row is None:
            raise KeyError(consent_id)
        return self._codec.decrypt(
            bytes(row[0]), context=f"consent_record:{consent_id}"
        )

    def create_session(
        self,
        session_id: str,
        *,
        subject_uuid: str,
        consent_id: str | None,
        lifecycle_status: str,
        versions_json: bytes,
        started_at_ns: int,
    ) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """INSERT INTO sessions(
                    session_id, subject_uuid, consent_id, lifecycle_status,
                    started_at_ns, versions_json
                ) VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    session_id,
                    subject_uuid,
                    consent_id,
                    lifecycle_status,
                    started_at_ns,
                    versions_json,
                ),
            )

    def add_segment(
        self,
        segment_id: str,
        *,
        session_id: str,
        relative_path: str,
        byte_count: int,
        state: str,
        sealed_at_ns: int,
        acknowledged_at_ns: int | None = None,
        retain_until_ns: int | None = None,
    ) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """INSERT INTO segments VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    segment_id,
                    session_id,
                    relative_path,
                    byte_count,
                    state,
                    sealed_at_ns,
                    acknowledged_at_ns,
                    retain_until_ns,
                ),
            )

    def add_upload_task(self, task_id: str, segment_id: str, *, state: str) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT INTO upload_tasks(upload_task_id, segment_id, state) VALUES (?, ?, ?)",
                (task_id, segment_id, state),
            )

    def register_sealed_segment(
        self,
        segment_id: str,
        *,
        session_id: str,
        relative_path: str,
        byte_count: int,
        sealed_at_ns: int,
    ) -> None:
        """Atomically register a verified sealed file and its pending upload."""

        with self._lock, self._connection:
            self._connection.execute(
                """INSERT OR IGNORE INTO segments
                (segment_id, session_id, relative_path, byte_count, state, sealed_at_ns)
                VALUES (?, ?, ?, ?, 'SEALED', ?)""",
                (segment_id, session_id, relative_path, byte_count, sealed_at_ns),
            )
            state = self._connection.execute(
                "SELECT state FROM segments WHERE segment_id=?", (segment_id,)
            ).fetchone()[0]
            if state != "SEALED":
                raise ValueError("only SEALED segments may enter the upload queue")
            self._connection.execute(
                """INSERT OR IGNORE INTO upload_tasks(upload_task_id, segment_id, state)
                VALUES (?, ?, 'PENDING')""",
                (f"upload:{segment_id}", segment_id),
            )

    def segment_state(self, segment_id: str) -> str:
        with self._lock:
            row = self._connection.execute(
                "SELECT state FROM segments WHERE segment_id=?", (segment_id,)
            ).fetchone()
        if row is None:
            raise KeyError(segment_id)
        return str(row[0])

    def upload_tasks_for_segment(self, segment_id: str) -> list[str]:
        with self._lock:
            rows = self._connection.execute(
                """SELECT state FROM upload_tasks WHERE segment_id=?
                ORDER BY upload_task_id""",
                (segment_id,),
            ).fetchall()
        return [str(row[0]) for row in rows]

    def recover_interrupted_state(self, *, recovered_at_ns: int) -> RecoveryResult:
        with self._lock, self._connection:
            sessions = self._connection.execute(
                """UPDATE sessions
                SET lifecycle_status='CLOSED', validity_status='INCOMPLETE', ended_at_ns=?
                WHERE lifecycle_status='ACQUIRING'""",
                (recovered_at_ns,),
            ).rowcount
            uploads = self._connection.execute(
                "UPDATE upload_tasks SET state='PENDING' WHERE state='UPLOADING'"
            ).rowcount
            telemetry = self._connection.execute(
                """UPDATE telemetry_events
                SET state='PENDING', attempt_count=attempt_count+1
                WHERE state='UPLOADING'"""
            ).rowcount
        return RecoveryResult(sessions, uploads, telemetry)

    def quarantine_segment_path(self, relative_path: str) -> int:
        """Make a verified-bad on-disk segment permanently ineligible for upload."""

        with self._lock, self._connection:
            rows = self._connection.execute(
                "SELECT segment_id FROM segments WHERE relative_path=?",
                (relative_path,),
            ).fetchall()
            if not rows:
                return 0
            segment_ids = [str(row[0]) for row in rows]
            placeholders = ", ".join("?" for _ in segment_ids)
            self._connection.execute(
                f"UPDATE segments SET state='CORRUPT' WHERE segment_id IN ({placeholders})",
                segment_ids,
            )
            self._connection.execute(
                f"UPDATE upload_tasks SET state='QUARANTINED' "
                f"WHERE segment_id IN ({placeholders})",
                segment_ids,
            )
            return len(segment_ids)

    def session_status(self, session_id: str) -> tuple[str, str, int | None]:
        with self._lock:
            row = self._connection.execute(
                """SELECT lifecycle_status, validity_status, ended_at_ns
                FROM sessions WHERE session_id=?""",
                (session_id,),
            ).fetchone()
        if row is None:
            raise KeyError(session_id)
        return str(row[0]), str(row[1]), row[2]

    def upload_state(self, task_id: str) -> str:
        with self._lock:
            row = self._connection.execute(
                "SELECT state FROM upload_tasks WHERE upload_task_id=?", (task_id,)
            ).fetchone()
        if row is None:
            raise KeyError(task_id)
        return str(row[0])

    def record_successful_online(self, observed_at_ns: int) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "UPDATE terminal_state SET last_successful_online_ns=? WHERE singleton=1",
                (observed_at_ns,),
            )

    def offline_snapshot(self) -> OfflineSnapshot:
        pending = ("SEALED", "PENDING_UPLOAD", "UPLOADING", "CORRUPT")
        with self._lock:
            row = self._connection.execute(
                """SELECT terminal_state.last_successful_online_ns,
                    COUNT(DISTINCT segments.session_id),
                    COALESCE(SUM(segments.byte_count), 0)
                FROM terminal_state
                LEFT JOIN segments ON segments.state IN (?, ?, ?, ?)
                WHERE terminal_state.singleton=1""",
                pending,
            ).fetchone()
        return OfflineSnapshot(row[0], int(row[1]), int(row[2]))

    def evaluate_new_test(
        self,
        *,
        now_ns: int,
        free_disk_bytes: int,
        estimated_test_bytes: int,
        reserve_bytes: int = 0,
    ) -> NewTestDecision:
        snapshot = self.offline_snapshot()
        reasons: list[GateReason] = []
        if (
            snapshot.last_successful_online_ns is None
            or now_ns - snapshot.last_successful_online_ns >= OFFLINE_LIMIT_NS
        ):
            reasons.append(GateReason.OFFLINE_TOO_LONG)
        if snapshot.pending_session_count >= PENDING_SESSION_LIMIT:
            reasons.append(GateReason.PENDING_SESSION_LIMIT)
        if snapshot.pending_bytes >= PENDING_BYTE_LIMIT:
            reasons.append(GateReason.PENDING_BYTE_LIMIT)
        if free_disk_bytes < estimated_test_bytes + reserve_bytes:
            reasons.append(GateReason.INSUFFICIENT_DISK)
        return NewTestDecision(not reasons, tuple(reasons))

    def cleanup_candidates(self, *, now_ns: int) -> list[CleanupCandidate]:
        with self._lock:
            rows = self._connection.execute(
                """SELECT segment_id, relative_path, byte_count FROM segments
                WHERE state='ACKNOWLEDGED' AND acknowledged_at_ns IS NOT NULL
                  AND retain_until_ns IS NOT NULL AND retain_until_ns <= ?
                ORDER BY sealed_at_ns, segment_id""",
                (now_ns,),
            ).fetchall()
        return [CleanupCandidate(str(row[0]), str(row[1]), int(row[2])) for row in rows]

    def finalize_segment_cleanup(self, segment_id: str, *, now_ns: int) -> None:
        with self._lock, self._connection:
            row = self._connection.execute(
                """SELECT state, acknowledged_at_ns, retain_until_ns
                FROM segments WHERE segment_id=?""",
                (segment_id,),
            ).fetchone()
            if row is None:
                raise KeyError(segment_id)
            if row[0] != "ACKNOWLEDGED" or row[1] is None or row[2] is None or row[2] > now_ns:
                raise ValueError("segment is not acknowledged and past retention")
            self._connection.execute(
                "DELETE FROM segments WHERE segment_id=?", (segment_id,)
            )

    def segment_exists(self, segment_id: str) -> bool:
        with self._lock:
            return (
                self._connection.execute(
                    "SELECT 1 FROM segments WHERE segment_id=?", (segment_id,)
                ).fetchone()
                is not None
            )
