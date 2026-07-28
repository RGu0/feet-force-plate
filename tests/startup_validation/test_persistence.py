from __future__ import annotations

import json
from pathlib import Path
import sqlite3

import pytest

from client.spool.state_store import SCHEMA_VERSION, SensitiveBlobCodec, StateStore
from client.startup_validation.models import (
    DeviceValidationRun,
    ValidationOutcome,
    ValidationReason,
)
from client.startup_validation.persistence import ValidationAuditTrail


class _Keys:
    def get_key(self) -> bytes:
        return b"k" * 32


def _run(
    *,
    run_id: str = "run-1",
    previous_run_id: str | None = None,
    attempt: int = 1,
    outcome: ValidationOutcome = ValidationOutcome.RETRYABLE_FAIL,
    reason: ValidationReason | None = ValidationReason.SIGNAL_INVALID,
    device_ref: str = "ch340-0123456789abcdef0123",
) -> DeviceValidationRun:
    return DeviceValidationRun(
        validation_run_id=run_id,
        previous_validation_run_id=previous_run_id,
        terminal_id="terminal-opaque-1",
        device_ref=device_ref,
        attempt_number=attempt,
        app_version="0.1.0-test",
        protocol_version="do-p4864-observed-compact-8bit/1",
        data_mode_version="48x64-uint8-column-major/1",
        rules_version="startup-baseline/1",
        threshold_version="startup-baseline-thresholds/1",
        started_at_wall_ns=10,
        completed_at_wall_ns=20,
        outcome=outcome,
        reason=reason,
        error_code=None if reason is None else "E-DEV-109",
        diagnostic_id=f"diagnostic-{run_id}",
        statistics=None,
        transition_names=("CONNECTING", "SIGNAL_INVALID"),
        partial_window_discarded=reason is not None,
    )


@pytest.fixture
def store(tmp_path: Path):
    repository = StateStore(
        tmp_path / "state.sqlite3",
        SensitiveBlobCodec(_Keys()),
    )
    yield repository
    repository.close()


def test_migration_adds_versioned_validation_audit_and_telemetry_queue(store) -> None:
    assert store.schema_version == SCHEMA_VERSION
    assert {"device_validation_runs", "telemetry_events"}.issubset(
        store.table_names()
    )


def test_audit_trail_persists_only_safe_versioned_summary_and_pending_event(store) -> None:
    trail = ValidationAuditTrail(
        store,
        event_id_factory=lambda: "event-1",
        wall_time_ns=lambda: 30,
    )

    event_id = trail.record(_run())

    assert event_id == "event-1"
    payload = json.loads(store.validation_run_payload("run-1"))
    assert payload["schema_version"] == "device-validation-run/1"
    assert payload["versions"]["threshold"] == "startup-baseline-thresholds/1"
    assert "thresholds" not in payload
    assert "raw_frames" not in payload
    assert "matrix" not in payload
    pending = store.pending_telemetry_events(limit=10)
    assert [(item.event_id, item.state, item.attempt_count) for item in pending] == [
        ("event-1", "PENDING", 0)
    ]
    assert json.loads(pending[0].payload_json) == payload


def test_upload_failure_requeues_without_mutating_local_audit(store) -> None:
    trail = ValidationAuditTrail(
        store,
        event_id_factory=lambda: "event-1",
        wall_time_ns=lambda: 30,
    )
    trail.record(_run())

    trail.mark_uploading("event-1")
    trail.mark_upload_failed("event-1")

    pending = store.pending_telemetry_events(limit=10)
    assert [(item.event_id, item.state, item.attempt_count) for item in pending] == [
        ("event-1", "PENDING", 1)
    ]
    assert json.loads(store.validation_run_payload("run-1"))["outcome"] == "RETRYABLE_FAIL"


def test_audit_rejects_raw_device_paths_and_does_not_accept_arbitrary_debug_data(store) -> None:
    trail = ValidationAuditTrail(store)

    with pytest.raises(ValueError, match="opaque"):
        trail.record(_run(device_ref="/dev/cu.usbserial-private"))

    database_bytes = store.path.read_bytes()
    assert b"usbserial-private" not in database_bytes
    assert b"person@example.invalid" not in database_bytes
    assert b"Traceback" not in database_bytes


def test_retry_chain_is_queryable_in_newest_first_order(store) -> None:
    ids = iter(("event-1", "event-2", "event-3"))
    trail = ValidationAuditTrail(
        store,
        event_id_factory=lambda: next(ids),
        wall_time_ns=lambda: 30,
    )
    trail.record(_run(run_id="run-1"))
    trail.record(_run(run_id="run-2", previous_run_id="run-1", attempt=2))
    trail.record(
        _run(
            run_id="run-3",
            previous_run_id="run-2",
            attempt=3,
            outcome=ValidationOutcome.PASS,
            reason=None,
        )
    )

    recent = trail.recent_results("ch340-0123456789abcdef0123", limit=3)

    assert [item.validation_run_id for item in recent] == ["run-3", "run-2", "run-1"]
    assert recent[0].outcome is ValidationOutcome.PASS
    assert recent[1].reason is ValidationReason.SIGNAL_INVALID


def test_existing_schema_one_database_migrates_without_losing_old_table(tmp_path) -> None:
    path = tmp_path / "existing.sqlite3"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE existing_marker(value TEXT NOT NULL)")
    connection.execute("INSERT INTO existing_marker VALUES ('preserved')")
    connection.execute("PRAGMA user_version=1")
    connection.commit()
    connection.close()

    migrated = StateStore(path, SensitiveBlobCodec(_Keys()))
    try:
        assert migrated.schema_version == SCHEMA_VERSION
        assert "existing_marker" in migrated.table_names()
        assert {"device_validation_runs", "telemetry_events"}.issubset(
            migrated.table_names()
        )
    finally:
        migrated.close()


def test_startup_recovery_requeues_interrupted_telemetry_with_attempt(store) -> None:
    trail = ValidationAuditTrail(
        store,
        event_id_factory=lambda: "event-1",
        wall_time_ns=lambda: 30,
    )
    trail.record(_run())
    trail.mark_uploading("event-1")

    result = store.recover_interrupted_state(recovered_at_ns=40)

    assert result.telemetry_requeued == 1
    assert [
        (item.event_id, item.attempt_count)
        for item in store.pending_telemetry_events(limit=10)
    ] == [("event-1", 1)]
