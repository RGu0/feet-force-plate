"""Dynamic sensor-defect evidence and frozen device health masks.

A low raw value alone is not evidence of a bad sensor: a foot can simply be
elsewhere.  This module only accumulates evidence when neighbouring cells are
loaded and changing while the candidate cell remains abnormally unresponsive.
The resulting mask is a per-device configuration snapshot; callers freeze it
at session start and persist it outside the raw-frame archive.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
from math import isfinite
import os
from pathlib import Path
import sqlite3
import time
import uuid

import numpy as np
from numpy.typing import NDArray


class DynamicDefectStatus(StrEnum):
    SUSPECT = "SUSPECT"
    REPAIRABLE = "REPAIRABLE"


class DeviceHealthStatus(StrEnum):
    READY = "READY"
    HEALTH_UNAVAILABLE = "HEALTH_UNAVAILABLE"


class DeviceHealthEventType(StrEnum):
    """Desensitized hardware-health events retained for internal support only."""

    MASK_UPDATED = "MASK_UPDATED"
    HEALTH_UNAVAILABLE = "HEALTH_UNAVAILABLE"
    RECOVERY_CANDIDATE = "RECOVERY_CANDIDATE"


@dataclass(frozen=True, slots=True)
class DynamicDefectPolicy:
    """Versioned thresholds for evidence, promotion and device availability."""

    version: str = "dynamic-defect-mask/generic-grid/1"
    support_relative_threshold: float = 0.08
    response_fraction_limit: float = 0.20
    temporal_variation_fraction_limit: float = 0.25
    minimum_dynamic_range: float = 8.0
    minimum_opportunities: int = 5
    minimum_evidence_ratio: float = 0.80
    promotion_observations: int = 2
    maximum_repairable_cells: int = 2
    maximum_mask_fraction: float = 0.03

    def __post_init__(self) -> None:
        if not self.version:
            raise ValueError("dynamic defect policy version is required")
        for value in (
            self.support_relative_threshold,
            self.response_fraction_limit,
            self.temporal_variation_fraction_limit,
            self.minimum_evidence_ratio,
            self.maximum_mask_fraction,
        ):
            if not isfinite(value) or not 0 < value <= 1:
                raise ValueError("dynamic defect ratio thresholds must be within (0, 1]")
        if not isfinite(self.minimum_dynamic_range) or self.minimum_dynamic_range <= 0:
            raise ValueError("minimum_dynamic_range must be positive and finite")
        if self.minimum_opportunities < 1 or self.promotion_observations < 1:
            raise ValueError("dynamic defect evidence counts must be positive")
        if self.maximum_repairable_cells < 0:
            raise ValueError("maximum_repairable_cells must not be negative")


@dataclass(frozen=True, slots=True)
class DynamicDefectEntry:
    source_index: int
    status: DynamicDefectStatus
    confirmed_observations: int
    last_observed_session_id: str

    def __post_init__(self) -> None:
        if self.source_index < 0:
            raise ValueError("source_index must be non-negative")
        if self.confirmed_observations < 1:
            raise ValueError("confirmed_observations must be positive")
        if not self.last_observed_session_id:
            raise ValueError("last_observed_session_id is required")


@dataclass(frozen=True, slots=True)
class DeviceHealthEvent:
    """A raw-data-free, durable history entry for one physical device."""

    event_id: str
    device_id: str
    event_type: DeviceHealthEventType
    mask_version: int
    health_status: DeviceHealthStatus
    policy_version: str
    candidate_count: int
    repairable_count: int
    created_at_ns: int


class DeviceHealthAuditStore:
    """SQLite history for dynamic-mask changes and health-state transitions.

    This database is intentionally separate from valid clinical/session storage:
    it contains neither source matrices nor participant data.  It makes a
    device's mask evolution recoverable even when no session is ultimately
    promoted as a valid local session.
    """

    def __init__(self, data_root: str | Path) -> None:
        self.path = Path(data_root) / "hardware" / "device-health.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.path)
        try:
            self._connection.execute("PRAGMA journal_mode=WAL")
            self._connection.execute("PRAGMA synchronous=FULL")
            self._connection.execute("PRAGMA busy_timeout=5000")
            with self._connection:
                self._connection.execute(
                    """CREATE TABLE IF NOT EXISTS device_health_events (
                        event_id TEXT PRIMARY KEY,
                        device_id TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        mask_version INTEGER NOT NULL,
                        health_status TEXT NOT NULL,
                        policy_version TEXT NOT NULL,
                        candidate_count INTEGER NOT NULL,
                        repairable_count INTEGER NOT NULL,
                        created_at_ns INTEGER NOT NULL
                    )"""
                )
                self._connection.execute(
                    """CREATE INDEX IF NOT EXISTS idx_device_health_events_device_time
                    ON device_health_events(device_id, created_at_ns DESC, event_id DESC)"""
                )
        except Exception:
            self._connection.close()
            raise

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> DeviceHealthAuditStore:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def record(self, events: tuple[DeviceHealthEvent, ...]) -> None:
        if not events:
            return
        with self._connection:
            self._connection.executemany(
                """INSERT INTO device_health_events(
                    event_id, device_id, event_type, mask_version, health_status,
                    policy_version, candidate_count, repairable_count, created_at_ns
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        event.event_id,
                        event.device_id,
                        event.event_type.value,
                        event.mask_version,
                        event.health_status.value,
                        event.policy_version,
                        event.candidate_count,
                        event.repairable_count,
                        event.created_at_ns,
                    )
                    for event in events
                ],
            )

    def history(self, device_id: str, *, limit: int = 100) -> tuple[DeviceHealthEvent, ...]:
        if not device_id or limit <= 0:
            raise ValueError("device ID and positive history limit are required")
        rows = self._connection.execute(
            """SELECT event_id, device_id, event_type, mask_version, health_status,
                policy_version, candidate_count, repairable_count, created_at_ns
            FROM device_health_events WHERE device_id=?
            ORDER BY created_at_ns DESC, event_id DESC LIMIT ?""",
            (device_id, limit),
        ).fetchall()
        return tuple(
            DeviceHealthEvent(
                event_id=str(row[0]),
                device_id=str(row[1]),
                event_type=DeviceHealthEventType(str(row[2])),
                mask_version=int(row[3]),
                health_status=DeviceHealthStatus(str(row[4])),
                policy_version=str(row[5]),
                candidate_count=int(row[6]),
                repairable_count=int(row[7]),
                created_at_ns=int(row[8]),
            )
            for row in rows
        )


@dataclass(frozen=True, slots=True)
class DynamicDefectMask:
    """A frozen, JSON-compatible device-health mask without raw-frame content."""

    device_id: str
    mask_version: int
    policy_version: str
    shape: tuple[int, int]
    entries: tuple[DynamicDefectEntry, ...] = ()

    def __post_init__(self) -> None:
        if not self.device_id or not self.policy_version:
            raise ValueError("device ID and policy version are required")
        if self.mask_version < 0 or len(self.shape) != 2 or min(self.shape) < 3:
            raise ValueError("mask version and shape are invalid")
        total = self.shape[0] * self.shape[1]
        if any(entry.source_index >= total for entry in self.entries):
            raise ValueError("mask source index is outside the declared shape")
        if len({entry.source_index for entry in self.entries}) != len(self.entries):
            raise ValueError("mask source indexes must be unique")

    @property
    def repairable_source_indices(self) -> frozenset[int]:
        return frozenset(
            entry.source_index
            for entry in self.entries
            if entry.status is DynamicDefectStatus.REPAIRABLE
        )

    def health_status(self, policy: DynamicDefectPolicy) -> DeviceHealthStatus:
        repairable = self.repairable_source_indices
        if len(repairable) > policy.maximum_repairable_cells:
            return DeviceHealthStatus.HEALTH_UNAVAILABLE
        if len(repairable) / (self.shape[0] * self.shape[1]) > policy.maximum_mask_fraction:
            return DeviceHealthStatus.HEALTH_UNAVAILABLE
        coordinates = {divmod(index, self.shape[0]) for index in repairable}
        if any(
            abs(row - other_row) <= 1
            and abs(column - other_column) <= 1
            and (row, column) != (other_row, other_column)
            for row, column in coordinates
            for other_row, other_column in coordinates
        ):
            return DeviceHealthStatus.HEALTH_UNAVAILABLE
        return DeviceHealthStatus.READY

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "dynamic-defect-mask/2",
            "device_id": self.device_id,
            "mask_version": self.mask_version,
            "policy_version": self.policy_version,
            "shape": list(self.shape),
            "entries": [
                {
                    "source_index": entry.source_index,
                    "status": entry.status.value,
                    "confirmed_observations": entry.confirmed_observations,
                    "last_observed_session_id": entry.last_observed_session_id,
                }
                for entry in self.entries
            ],
        }

    @classmethod
    def from_dict(cls, payload: object) -> DynamicDefectMask:
        """Parse the persisted, versioned health mask without raw data."""

        if not isinstance(payload, dict):
            raise ValueError("unsupported dynamic defect mask schema")
        if payload.get("schema_version") == "dynamic-defect-mask/1":
            raise ValueError(
                "dynamic defect mask schema /1 has no stable device ID; assign a device ID before migration"
            )
        if payload.get("schema_version") != "dynamic-defect-mask/2":
            raise ValueError("unsupported dynamic defect mask schema")
        shape = payload.get("shape")
        entries = payload.get("entries")
        if (
            not isinstance(shape, list)
            or len(shape) != 2
            or any(isinstance(value, bool) or not isinstance(value, int) for value in shape)
            or not isinstance(entries, list)
        ):
            raise ValueError("dynamic defect mask shape or entries are invalid")
        return cls(
            device_id=_required_string(payload, "device_id"),
            mask_version=_required_int(payload, "mask_version"),
            policy_version=_required_string(payload, "policy_version"),
            shape=(shape[0], shape[1]),
            entries=tuple(
                DynamicDefectEntry(
                    source_index=_required_int(entry, "source_index"),
                    status=DynamicDefectStatus(_required_string(entry, "status")),
                    confirmed_observations=_required_int(
                        entry, "confirmed_observations"
                    ),
                    last_observed_session_id=_required_string(
                        entry, "last_observed_session_id"
                    ),
                )
                for entry in entries
                if isinstance(entry, dict)
            ),
        )


@dataclass(frozen=True, slots=True)
class DynamicDefectMaskStore:
    """Durable per-device mask store with atomic next-session updates.

    ``data_root`` is the application's writable data directory, never a source
    tree or documentation directory.  The stable physical ``device_id`` is
    SHA-256 mapped to a directory name, so it cannot escape the hardware folder.
    Same-model devices share their static specification but never their dynamic
    defect masks.
    """

    data_root: Path
    device_id: str
    shape: tuple[int, int]
    policy: DynamicDefectPolicy = DynamicDefectPolicy()

    def __post_init__(self) -> None:
        if not self.device_id or len(self.shape) != 2 or min(self.shape) < 3:
            raise ValueError("device ID and dynamic defect mask shape are required")

    @property
    def path(self) -> Path:
        device_digest = hashlib.sha256(self.device_id.encode("utf-8")).hexdigest()
        return (
            self.data_root
            / "hardware"
            / "do-p4864"
            / device_digest
            / "dynamic-defect-mask.json"
        )

    def load_for_session(self) -> DynamicDefectMask:
        """Load the immutable mask snapshot that a newly started session uses."""

        if not self.path.exists():
            return DynamicDefectMask(
                device_id=self.device_id,
                mask_version=0,
                policy_version=self.policy.version,
                shape=self.shape,
            )
        try:
            mask = DynamicDefectMask.from_dict(json.loads(self.path.read_text("utf-8")))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            raise ValueError("dynamic defect mask file is unreadable") from error
        if mask.device_id != self.device_id or mask.shape != self.shape:
            raise ValueError("dynamic defect mask does not match this device ID")
        return mask

    def update_after_session(
        self,
        frozen_mask: DynamicDefectMask,
        *,
        session_id: str,
        matrices: tuple[NDArray[np.number], ...],
    ) -> DynamicDefectObservation:
        """Create and atomically persist the next snapshot after a session ends."""

        current = self.load_for_session()
        if current.mask_version != frozen_mask.mask_version:
            raise ValueError("dynamic defect mask changed while this session was active")
        observation = observe_dynamic_defects(
            frozen_mask,
            session_id=session_id,
            matrices=matrices,
            policy=self.policy,
        )
        self._atomic_write(observation.updated_mask)
        self._record_health_events(current, observation)
        return observation

    def _record_health_events(
        self, previous: DynamicDefectMask, observation: DynamicDefectObservation
    ) -> None:
        """Persist a non-sensitive audit after the next mask is durably written."""

        updated = observation.updated_mask
        previous_health = previous.health_status(self.policy)
        updated_health = updated.health_status(self.policy)
        event_types: list[DeviceHealthEventType] = []
        if updated.mask_version != previous.mask_version:
            event_types.append(DeviceHealthEventType.MASK_UPDATED)
        if updated_health is DeviceHealthStatus.HEALTH_UNAVAILABLE:
            event_types.append(DeviceHealthEventType.HEALTH_UNAVAILABLE)
            if (
                previous_health is DeviceHealthStatus.HEALTH_UNAVAILABLE
                and not observation.candidate_source_indices
            ):
                event_types.append(DeviceHealthEventType.RECOVERY_CANDIDATE)
        if not event_types:
            return
        created_at_ns = time.time_ns()
        repairable_count = len(updated.repairable_source_indices)
        events = tuple(
            DeviceHealthEvent(
                event_id=str(uuid.uuid4()),
                device_id=self.device_id,
                event_type=event_type,
                mask_version=updated.mask_version,
                health_status=updated_health,
                policy_version=updated.policy_version,
                candidate_count=len(observation.candidate_source_indices),
                repairable_count=repairable_count,
                created_at_ns=created_at_ns,
            )
            for event_type in event_types
        )
        with DeviceHealthAuditStore(self.data_root) as audit:
            audit.record(events)

    def _atomic_write(self, mask: DynamicDefectMask) -> None:
        if mask.device_id != self.device_id or mask.shape != self.shape:
            raise ValueError("cannot write a dynamic defect mask for another device ID")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        encoded = json.dumps(mask.to_dict(), sort_keys=True, separators=(",", ":"))
        with temporary.open("w", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self.path)
        directory_fd = os.open(self.path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)


@dataclass(frozen=True, slots=True)
class DynamicDefectObservation:
    """One session's evidence and the next session's frozen mask snapshot."""

    candidate_source_indices: tuple[int, ...]
    opportunities_by_source_index: tuple[tuple[int, int], ...]
    updated_mask: DynamicDefectMask


def observe_dynamic_defects(
    mask: DynamicDefectMask,
    *,
    session_id: str,
    matrices: tuple[NDArray[np.number], ...],
    policy: DynamicDefectPolicy = DynamicDefectPolicy(),
) -> DynamicDefectObservation:
    """Evaluate a dynamic window and return a new frozen mask snapshot.

    The caller persists ``updated_mask`` only after its whole-session policy has
    completed.  This function does not alter raw arrays or modify the mask used
    by the session that supplied the matrices.
    """

    source = _validated_stack(matrices, mask.shape)
    candidates, opportunities = _dynamic_neighbour_candidates(source, policy)
    entries = {entry.source_index: entry for entry in mask.entries}
    changed = False
    for source_index in candidates:
        previous = entries.get(source_index)
        if previous is None:
            entries[source_index] = DynamicDefectEntry(
                source_index=source_index,
                status=DynamicDefectStatus.SUSPECT,
                confirmed_observations=1,
                last_observed_session_id=session_id,
            )
            changed = True
            continue
        if previous.last_observed_session_id == session_id:
            continue
        count = previous.confirmed_observations + 1
        status = (
            DynamicDefectStatus.REPAIRABLE
            if count >= policy.promotion_observations
            else DynamicDefectStatus.SUSPECT
        )
        entries[source_index] = DynamicDefectEntry(
            source_index=source_index,
            status=status,
            confirmed_observations=count,
            last_observed_session_id=session_id,
        )
        changed = True
    updated = DynamicDefectMask(
        device_id=mask.device_id,
        mask_version=mask.mask_version + int(changed),
        policy_version=policy.version,
        shape=mask.shape,
        entries=tuple(sorted(entries.values(), key=lambda entry: entry.source_index)),
    )
    return DynamicDefectObservation(
        candidate_source_indices=tuple(sorted(candidates)),
        opportunities_by_source_index=tuple(sorted(opportunities.items())),
        updated_mask=updated,
    )


def _validated_stack(
    matrices: tuple[NDArray[np.number], ...], shape: tuple[int, int]
) -> NDArray[np.float64]:
    if len(matrices) < 2:
        raise ValueError("dynamic defect detection requires at least two frames")
    stack = np.asarray(matrices, dtype=np.float64)
    if stack.shape[1:] != shape:
        raise ValueError("dynamic defect matrices must match the frozen mask shape")
    if not np.all(np.isfinite(stack)) or np.any(stack < 0):
        raise ValueError("dynamic defect matrices must be finite and non-negative")
    return stack


def _dynamic_neighbour_candidates(
    stack: NDArray[np.float64], policy: DynamicDefectPolicy
) -> tuple[set[int], dict[int, int]]:
    frame_p99 = np.percentile(stack, 99, axis=(1, 2))
    if float(frame_p99.max() - frame_p99.min()) < policy.minimum_dynamic_range:
        return set(), {}
    dynamic_range = np.percentile(stack, 95, axis=0) - np.percentile(stack, 5, axis=0)
    candidates: set[int] = set()
    opportunities: dict[int, int] = {}
    rows, columns = stack.shape[1:]
    for row in range(1, rows - 1):
        for column in range(1, columns - 1):
            support = _two_sided_support(stack, row, column, frame_p99, policy)
            count = int(np.count_nonzero(support))
            if count < policy.minimum_opportunities:
                continue
            opportunities[column * rows + row] = count
            neighbours = np.maximum(
                np.minimum(stack[:, row - 1, column], stack[:, row + 1, column]),
                np.minimum(stack[:, row, column - 1], stack[:, row, column + 1]),
            )
            low_response = stack[:, row, column] <= neighbours * policy.response_fraction_limit
            evidence_ratio = float(np.count_nonzero(support & low_response)) / count
            neighbour_range = max(
                dynamic_range[row - 1, column],
                dynamic_range[row + 1, column],
                dynamic_range[row, column - 1],
                dynamic_range[row, column + 1],
            )
            temporal_mismatch = dynamic_range[row, column] <= (
                neighbour_range * policy.temporal_variation_fraction_limit
            )
            if evidence_ratio >= policy.minimum_evidence_ratio and temporal_mismatch:
                candidates.add(column * rows + row)
    return candidates, opportunities


def _two_sided_support(
    stack: NDArray[np.float64],
    row: int,
    column: int,
    frame_p99: NDArray[np.float64],
    policy: DynamicDefectPolicy,
) -> NDArray[np.bool_]:
    threshold = frame_p99 * policy.support_relative_threshold
    vertical = (stack[:, row - 1, column] >= threshold) & (
        stack[:, row + 1, column] >= threshold
    )
    horizontal = (stack[:, row, column - 1] >= threshold) & (
        stack[:, row, column + 1] >= threshold
    )
    return vertical | horizontal


def _required_string(payload: object, name: str) -> str:
    if not isinstance(payload, dict):
        raise ValueError("dynamic defect mask entry must be an object")
    value = payload.get(name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"dynamic defect mask {name} must be a non-empty string")
    return value


def _required_int(payload: object, name: str) -> int:
    if not isinstance(payload, dict):
        raise ValueError("dynamic defect mask entry must be an object")
    value = payload.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"dynamic defect mask {name} must be an integer")
    return value
