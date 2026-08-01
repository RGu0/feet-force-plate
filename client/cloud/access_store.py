"""Non-secret desktop access cache with OS credential-store refresh tokens."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import os
from pathlib import Path
import sqlite3
import threading
from typing import Protocol
from uuid import UUID

from shared.contracts.access_control import AccessSession, SignedLicenseV2


LOCK_TIMEOUT_OPTIONS = frozenset({None, 5, 15, 30, 60})


class CredentialStore(Protocol):
    def set_refresh_token(self, account_id: UUID, refresh_token: str) -> None: ...

    def get_refresh_token(self, account_id: UUID) -> str | None: ...

    def delete_refresh_token(self, account_id: UUID) -> None: ...


class KeyringCredentialStore:
    def __init__(
        self,
        *,
        service_name: str = "FeetForcePlate.access",
        backend=None,
    ) -> None:
        if backend is None:
            import keyring

            backend = keyring
        self._service_name = service_name
        self._backend = backend

    @staticmethod
    def _username(account_id: UUID) -> str:
        return f"refresh:{account_id}"

    def set_refresh_token(self, account_id: UUID, refresh_token: str) -> None:
        self._backend.set_password(
            self._service_name,
            self._username(account_id),
            refresh_token,
        )

    def get_refresh_token(self, account_id: UUID) -> str | None:
        return self._backend.get_password(
            self._service_name,
            self._username(account_id),
        )

    def delete_refresh_token(self, account_id: UUID) -> None:
        try:
            self._backend.delete_password(
                self._service_name,
                self._username(account_id),
            )
        except Exception as exc:
            # keyring backends use backend-specific "not found" exceptions.
            if "not found" not in str(exc).lower():
                raise


@dataclass(frozen=True, slots=True)
class StoredAccessState:
    tenant_id: UUID
    account_id: UUID
    license_id: UUID
    hardware_id: str
    client_installation_id: UUID
    signed_license: SignedLicenseV2
    license_version: int
    last_trusted_server_utc: datetime | None
    trusted_wall_utc: datetime | None
    trusted_monotonic_ns: int | None
    lock_timeout_minutes: int | None


class ClientAccessStore:
    """Dedicated access SQLite store; secrets are delegated to OS keyring."""

    _ROLLBACK_TOLERANCE = timedelta(minutes=5)

    def __init__(self, path: str | Path, credentials: CredentialStore) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._credentials = credentials
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA synchronous=FULL")
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS access_state (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                tenant_id TEXT NOT NULL,
                account_id TEXT NOT NULL,
                license_id TEXT NOT NULL,
                hardware_id TEXT NOT NULL,
                client_installation_id TEXT NOT NULL,
                signed_license_json TEXT NOT NULL,
                license_version INTEGER NOT NULL CHECK (license_version > 0),
                last_trusted_server_utc TEXT,
                trusted_wall_utc TEXT,
                trusted_monotonic_ns INTEGER,
                lock_timeout_minutes INTEGER,
                CHECK (lock_timeout_minutes IS NULL OR lock_timeout_minutes IN (5,15,30,60))
            );
            """
        )
        self._connection.commit()
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def close(self) -> None:
        with self._lock:
            self._connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self._connection.close()

    def save_session(
        self,
        session: AccessSession,
        *,
        trusted_server_utc: datetime,
        observed_wall_utc: datetime,
        observed_monotonic_ns: int,
    ) -> StoredAccessState:
        server_utc = _aware_utc(trusted_server_utc)
        wall_utc = _aware_utc(observed_wall_utc)
        if observed_monotonic_ns < 0:
            raise ValueError("observed_monotonic_ns must be non-negative")
        prior = self.load()
        if (
            prior is not None
            and prior.account_id != session.account_id
            and self._credentials.get_refresh_token(prior.account_id) is not None
        ):
            self._credentials.delete_refresh_token(prior.account_id)
        signed_json = session.signed_license.model_dump_json()
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO access_state (
                    singleton, tenant_id, account_id, license_id, hardware_id,
                    client_installation_id, signed_license_json, license_version,
                    last_trusted_server_utc, trusted_wall_utc, trusted_monotonic_ns,
                    lock_timeout_minutes
                ) VALUES (1,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(singleton) DO UPDATE SET
                    tenant_id=excluded.tenant_id,
                    account_id=excluded.account_id,
                    license_id=excluded.license_id,
                    hardware_id=excluded.hardware_id,
                    client_installation_id=excluded.client_installation_id,
                    signed_license_json=excluded.signed_license_json,
                    license_version=excluded.license_version,
                    last_trusted_server_utc=excluded.last_trusted_server_utc,
                    trusted_wall_utc=excluded.trusted_wall_utc,
                    trusted_monotonic_ns=excluded.trusted_monotonic_ns
                """,
                (
                    str(session.tenant_id),
                    str(session.account_id),
                    str(session.license_id),
                    session.hardware_id,
                    str(session.client_installation_id),
                    signed_json,
                    session.signed_license.document.version,
                    _encode_datetime(server_utc),
                    _encode_datetime(wall_utc),
                    observed_monotonic_ns,
                    30 if prior is None else prior.lock_timeout_minutes,
                ),
            )
        self._credentials.set_refresh_token(session.account_id, session.refresh_token)
        loaded = self.load()
        assert loaded is not None
        return loaded

    def load(self) -> StoredAccessState | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM access_state WHERE singleton=1"
            ).fetchone()
        if row is None:
            return None
        signed = SignedLicenseV2.model_validate_json(row["signed_license_json"])
        return StoredAccessState(
            tenant_id=UUID(row["tenant_id"]),
            account_id=UUID(row["account_id"]),
            license_id=UUID(row["license_id"]),
            hardware_id=row["hardware_id"],
            client_installation_id=UUID(row["client_installation_id"]),
            signed_license=signed,
            license_version=row["license_version"],
            last_trusted_server_utc=_decode_datetime(row["last_trusted_server_utc"]),
            trusted_wall_utc=_decode_datetime(row["trusted_wall_utc"]),
            trusted_monotonic_ns=row["trusted_monotonic_ns"],
            lock_timeout_minutes=row["lock_timeout_minutes"],
        )

    def refresh_token(self) -> str | None:
        state = self.load()
        if state is None:
            return None
        return self._credentials.get_refresh_token(state.account_id)

    def clear_credentials(self) -> None:
        state = self.load()
        if state is not None:
            self._credentials.delete_refresh_token(state.account_id)

    def set_lock_timeout(self, minutes: int | None) -> None:
        if minutes not in LOCK_TIMEOUT_OPTIONS:
            raise ValueError("unsupported lock timeout")
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "UPDATE access_state SET lock_timeout_minutes=? WHERE singleton=1",
                (minutes,),
            )
        if cursor.rowcount != 1:
            raise RuntimeError("access state is not initialized")

    def clock_is_trusted(
        self,
        *,
        observed_wall_utc: datetime,
        observed_monotonic_ns: int,
    ) -> bool:
        state = self.load()
        if (
            state is None
            or state.last_trusted_server_utc is None
            or state.trusted_wall_utc is None
            or state.trusted_monotonic_ns is None
            or observed_monotonic_ns < state.trusted_monotonic_ns
        ):
            return False
        wall = _aware_utc(observed_wall_utc)
        if wall < state.trusted_wall_utc - self._ROLLBACK_TOLERANCE:
            return False
        elapsed = timedelta(
            microseconds=(observed_monotonic_ns - state.trusted_monotonic_ns) / 1000
        )
        expected_wall = state.trusted_wall_utc + elapsed
        return wall >= expected_wall - self._ROLLBACK_TOLERANCE


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(UTC)


def _encode_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return _aware_utc(value).isoformat().replace("+00:00", "Z")


def _decode_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


__all__ = [
    "ClientAccessStore",
    "CredentialStore",
    "KeyringCredentialStore",
    "LOCK_TIMEOUT_OPTIONS",
    "StoredAccessState",
]
