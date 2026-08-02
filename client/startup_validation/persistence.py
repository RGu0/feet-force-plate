from __future__ import annotations

from collections.abc import Callable
import json
import re
import time
import uuid

from client.spool.state_store import StateStore, TelemetryEvent

from .models import DeviceValidationRun, ValidationOutcome, ValidationReason
from .recovery import HistoricalValidationResult


TELEMETRY_SCHEMA_VERSION = "device-validation-telemetry/1"
_OPAQUE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{2,127}$")


class ValidationAuditTrail:
    """Persist and queue the allow-listed, raw-frame-free validation summary."""

    def __init__(
        self,
        store: StateStore,
        *,
        event_id_factory: Callable[[], str] = lambda: str(uuid.uuid4()),
        wall_time_ns: Callable[[], int] = time.time_ns,
    ) -> None:
        self._store = store
        self._event_id_factory = event_id_factory
        self._wall_time_ns = wall_time_ns

    def record(self, run: DeviceValidationRun) -> str:
        self._validate_opaque_ref(run.terminal_id, "terminal_id")
        self._validate_opaque_ref(run.device_ref, "device_ref")
        payload = run.safe_summary()
        payload_json = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        event_id = self._event_id_factory()
        self._store.record_validation_audit(
            validation_run_id=run.validation_run_id,
            previous_validation_run_id=run.previous_validation_run_id,
            terminal_id=run.terminal_id,
            device_ref=run.device_ref,
            attempt_number=run.attempt_number,
            outcome=run.outcome.value,
            reason=None if run.reason is None else run.reason.value,
            error_code=run.error_code,
            diagnostic_id=run.diagnostic_id,
            schema_version=run.schema_version,
            payload_json=payload_json,
            started_at_ns=run.started_at_wall_ns,
            completed_at_ns=run.completed_at_wall_ns,
            telemetry_event_id=event_id,
            telemetry_schema_version=TELEMETRY_SCHEMA_VERSION,
            created_at_ns=self._wall_time_ns(),
        )
        return event_id

    def recent_results(
        self,
        device_ref: str,
        *,
        limit: int,
    ) -> tuple[HistoricalValidationResult, ...]:
        return tuple(
            HistoricalValidationResult(
                validation_run_id=item.validation_run_id,
                outcome=ValidationOutcome(item.outcome),
                reason=None if item.reason is None else ValidationReason(item.reason),
            )
            for item in self._store.recent_validation_results(
                device_ref,
                limit=limit,
            )
        )

    def pending_events(self, *, limit: int = 50) -> tuple[TelemetryEvent, ...]:
        return tuple(self._store.pending_telemetry_events(limit=limit))

    def mark_uploading(self, event_id: str) -> None:
        self._store.set_telemetry_event_state(event_id, state="UPLOADING")

    def mark_upload_failed(self, event_id: str) -> None:
        self._store.set_telemetry_event_state(
            event_id,
            state="PENDING",
            increment_attempt=True,
        )

    def mark_uploaded(self, event_id: str) -> None:
        self._store.set_telemetry_event_state(event_id, state="ACKNOWLEDGED")

    def mark_quarantined(self, event_id: str) -> None:
        self._store.set_telemetry_event_state(event_id, state="QUARANTINED")

    @staticmethod
    def _validate_opaque_ref(value: str, field: str) -> None:
        if not _OPAQUE_REF.fullmatch(value):
            raise ValueError(f"{field} must be an opaque identifier")
