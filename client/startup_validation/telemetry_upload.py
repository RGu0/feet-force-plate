from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import json
import threading
from typing import Protocol
from uuid import UUID

import httpx
from pydantic import ValidationError

from shared.contracts.validation_telemetry import (
    DeviceValidationTelemetryBatchRequest,
    DeviceValidationTelemetryEvent,
    DeviceValidationTelemetryReceipt,
)

from .persistence import ValidationAuditTrail


class ValidationTelemetryUploadClient(Protocol):
    def upload(
        self,
        request: DeviceValidationTelemetryBatchRequest,
    ) -> tuple[UUID, ...]: ...


@dataclass(frozen=True, slots=True)
class ValidationTelemetryUploadCycle:
    uploaded: int
    requeued: int
    quarantined: int


class ValidationTelemetryCloudClient:
    """Authenticated HTTP boundary for privacy-validated startup telemetry."""

    def __init__(
        self,
        base_url: str,
        *,
        access_token_provider: Callable[[], str],
        verify: bool | str = True,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._access_token_provider = access_token_provider
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            verify=verify,
            transport=transport,
            timeout=httpx.Timeout(connect=5.0, read=20.0, write=20.0, pool=5.0),
        )

    def close(self) -> None:
        self._client.close()

    def upload(
        self,
        request: DeviceValidationTelemetryBatchRequest,
    ) -> tuple[UUID, ...]:
        token = self._access_token_provider()
        try:
            response = self._client.post(
                "/v1/telemetry/device-validation",
                headers={"Authorization": f"Bearer {token}"},
                json=request.model_dump(mode="json"),
            )
            response.raise_for_status()
            envelope = response.json()
            receipt = DeviceValidationTelemetryReceipt.model_validate(envelope["data"])
        except (httpx.HTTPError, KeyError, TypeError, ValueError, ValidationError) as exc:
            raise ConnectionError("validation telemetry upload failed") from exc
        return receipt.acknowledged_event_ids


class ValidationTelemetryUploadWorker:
    """Drain the durable queue without letting telemetry affect startup behavior."""

    def __init__(
        self,
        audit_trail: ValidationAuditTrail,
        client: ValidationTelemetryUploadClient,
        *,
        client_installation_id: UUID,
        batch_size: int = 50,
    ) -> None:
        if batch_size < 1 or batch_size > 50:
            raise ValueError("batch_size must be between 1 and 50")
        self._audit_trail = audit_trail
        self._client = client
        self._client_installation_id = client_installation_id
        self._batch_size = batch_size

    def run_once(self) -> ValidationTelemetryUploadCycle:
        events = self._audit_trail.pending_events(limit=self._batch_size)
        valid: list[DeviceValidationTelemetryEvent] = []
        quarantined = 0
        for event in events:
            try:
                payload = json.loads(event.payload_json)
                validated = DeviceValidationTelemetryEvent.model_validate(
                    {
                        "event_id": event.event_id,
                        "schema_version": event.schema_version,
                        "created_at_ns": event.created_at_ns,
                        "attempt_count": event.attempt_count,
                        "payload": payload,
                    }
                )
                if validated.payload.terminal_id != self._client_installation_id:
                    raise ValueError("queued telemetry belongs to another installation")
            except (UnicodeDecodeError, json.JSONDecodeError, ValidationError, ValueError):
                self._audit_trail.mark_quarantined(event.event_id)
                quarantined += 1
                continue
            valid.append(validated)

        if not valid:
            return ValidationTelemetryUploadCycle(0, 0, quarantined)

        for event in valid:
            self._audit_trail.mark_uploading(str(event.event_id))
        request = DeviceValidationTelemetryBatchRequest(
            client_installation_id=self._client_installation_id,
            events=tuple(valid),
        )
        expected = tuple(event.event_id for event in valid)
        try:
            acknowledged = self._client.upload(request)
            if set(acknowledged) != set(expected):
                raise ConnectionError("telemetry acknowledgement mismatch")
        except Exception:
            for event in valid:
                self._audit_trail.mark_upload_failed(str(event.event_id))
            return ValidationTelemetryUploadCycle(0, len(valid), quarantined)

        for event in valid:
            self._audit_trail.mark_uploaded(str(event.event_id))
        return ValidationTelemetryUploadCycle(len(valid), 0, quarantined)


def validation_telemetry_retry_delay(
    interval_seconds: float,
    *,
    consecutive_failures: int,
    maximum_seconds: float = 300.0,
) -> float:
    """Return bounded exponential retry delay; success resets to the base interval."""

    if interval_seconds <= 0 or maximum_seconds < interval_seconds:
        raise ValueError("invalid validation telemetry retry interval")
    if consecutive_failures < 0:
        raise ValueError("consecutive_failures cannot be negative")
    exponent = max(0, consecutive_failures - 1)
    return min(maximum_seconds, interval_seconds * (2**exponent))


class AutomaticValidationTelemetryWorker:
    """Run upload cycles on a daemon thread, immediately and then periodically."""

    def __init__(
        self,
        worker: ValidationTelemetryUploadWorker,
        *,
        interval_seconds: float = 30.0,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        self._worker = worker
        self._interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="validation-telemetry-upload",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=1.0)

    def _run(self) -> None:
        consecutive_failures = 0
        while not self._stop.is_set():
            try:
                cycle = self._worker.run_once()
                consecutive_failures = (
                    consecutive_failures + 1 if cycle.requeued else 0
                )
            except Exception:
                consecutive_failures += 1
            self._stop.wait(
                validation_telemetry_retry_delay(
                    self._interval_seconds,
                    consecutive_failures=consecutive_failures,
                )
            )
