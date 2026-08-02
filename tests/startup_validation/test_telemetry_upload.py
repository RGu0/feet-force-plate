from __future__ import annotations

import json
from pathlib import Path
import time
from uuid import UUID

import httpx
import pytest

from client.spool.state_store import SensitiveBlobCodec, StateStore
from client.startup_validation.models import (
    DeviceValidationRun,
    ValidationOutcome,
    ValidationReason,
)
from client.startup_validation.persistence import ValidationAuditTrail
from client.startup_validation.telemetry_upload import (
    AutomaticValidationTelemetryWorker,
    ValidationTelemetryCloudClient,
    ValidationTelemetryUploadWorker,
    validation_telemetry_retry_delay,
)


class _Keys:
    def get_key(self) -> bytes:
        return b"t" * 32


def _run() -> DeviceValidationRun:
    return DeviceValidationRun(
        validation_run_id="8ddcb66e-d1d7-4dfa-998f-018dfb194a2b",
        previous_validation_run_id=None,
        terminal_id="c03732ad-c781-4364-9d3a-c3ce3ea8488c",
        device_ref="hardware-0123456789abcdef0123",
        attempt_number=1,
        app_version="0.1.0-test",
        protocol_version="do-p4864-observed-compact-8bit/1",
        data_mode_version="48x64-uint8-column-major/1",
        rules_version="startup-baseline/1",
        threshold_version="startup-baseline-thresholds/1",
        started_at_wall_ns=10,
        completed_at_wall_ns=20,
        outcome=ValidationOutcome.RETRYABLE_FAIL,
        reason=ValidationReason.DEVICE_BUSY,
        error_code="E-DEV-102",
        diagnostic_id="86217533-9b9f-405d-9977-23cda4a8d003",
        statistics=None,
        transition_names=("BOOTSTRAPPING", "DEVICE_BUSY"),
        partial_window_discarded=False,
    )


@pytest.fixture
def store(tmp_path: Path):
    repository = StateStore(
        tmp_path / "state.sqlite3",
        SensitiveBlobCodec(_Keys()),
    )
    yield repository
    repository.close()


class _RecordingClient:
    def __init__(self, *, failures: int = 0) -> None:
        self.failures = failures
        self.requests = []

    def upload(self, request):
        self.requests.append(request)
        if self.failures:
            self.failures -= 1
            raise ConnectionError("offline with password=must-not-leak")
        return tuple(event.event_id for event in request.events)


def test_offline_upload_requeues_then_acknowledges_without_mutating_audit(store) -> None:
    trail = ValidationAuditTrail(
        store,
        event_id_factory=lambda: "a02694ec-c62f-4bd4-be33-bbb6859b0540",
        wall_time_ns=lambda: 30,
    )
    trail.record(_run())
    client = _RecordingClient(failures=1)
    worker = ValidationTelemetryUploadWorker(
        trail,
        client,
        client_installation_id=UUID("c03732ad-c781-4364-9d3a-c3ce3ea8488c"),
    )

    first = worker.run_once()
    second = worker.run_once()

    assert (first.uploaded, first.requeued, first.quarantined) == (0, 1, 0)
    assert (second.uploaded, second.requeued, second.quarantined) == (1, 0, 0)
    assert store.telemetry_event_state("a02694ec-c62f-4bd4-be33-bbb6859b0540") == (
        "ACKNOWLEDGED",
        1,
    )
    assert json.loads(store.validation_run_payload(str(_run().validation_run_id)))[
        "outcome"
    ] == "RETRYABLE_FAIL"


def test_polluted_legacy_event_is_quarantined_without_network_request(store) -> None:
    payload = {**_run().safe_summary(), "institution_record_number": "MRN-000085"}
    store.record_validation_audit(
        validation_run_id=_run().validation_run_id,
        previous_validation_run_id=None,
        terminal_id=_run().terminal_id,
        device_ref=_run().device_ref,
        attempt_number=1,
        outcome="RETRYABLE_FAIL",
        reason="DEVICE_BUSY",
        error_code="E-DEV-102",
        diagnostic_id=_run().diagnostic_id,
        schema_version="device-validation-run/1",
        payload_json=json.dumps(payload).encode("utf-8"),
        started_at_ns=10,
        completed_at_ns=20,
        telemetry_event_id="a02694ec-c62f-4bd4-be33-bbb6859b0540",
        telemetry_schema_version="device-validation-telemetry/1",
        created_at_ns=30,
    )
    client = _RecordingClient()
    worker = ValidationTelemetryUploadWorker(
        ValidationAuditTrail(store),
        client,
        client_installation_id=UUID("c03732ad-c781-4364-9d3a-c3ce3ea8488c"),
    )

    result = worker.run_once()

    assert (result.uploaded, result.requeued, result.quarantined) == (0, 0, 1)
    assert client.requests == []
    assert store.telemetry_event_state("a02694ec-c62f-4bd4-be33-bbb6859b0540") == (
        "QUARANTINED",
        0,
    )


def test_authenticated_http_client_sends_only_strict_batch_and_safe_errors(store) -> None:
    trail = ValidationAuditTrail(
        store,
        event_id_factory=lambda: "a02694ec-c62f-4bd4-be33-bbb6859b0540",
        wall_time_ns=lambda: 30,
    )
    trail.record(_run())
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            202,
            json={
                "data": {
                    "schema_version": "device-validation-telemetry-receipt/1",
                    "acknowledged_event_ids": [
                        "a02694ec-c62f-4bd4-be33-bbb6859b0540"
                    ],
                    "idempotent_replays": 0,
                },
                "meta": {},
            },
        )

    client = ValidationTelemetryCloudClient(
        "https://cloud.test",
        access_token_provider=lambda: "access-token-value-at-least-20",
        transport=httpx.MockTransport(handler),
    )
    worker = ValidationTelemetryUploadWorker(
        trail,
        client,
        client_installation_id=UUID("c03732ad-c781-4364-9d3a-c3ce3ea8488c"),
    )
    try:
        result = worker.run_once()
    finally:
        client.close()

    assert result.uploaded == 1
    assert len(captured) == 1
    assert captured[0].url.path == "/v1/telemetry/device-validation"
    assert captured[0].headers["Authorization"] == "Bearer access-token-value-at-least-20"
    body = json.loads(captured[0].content)
    assert body["client_installation_id"] == "c03732ad-c781-4364-9d3a-c3ce3ea8488c"
    assert "institution_record_number" not in json.dumps(body)


def test_background_worker_uploads_pending_event_without_blocking_caller(store) -> None:
    trail = ValidationAuditTrail(
        store,
        event_id_factory=lambda: "a02694ec-c62f-4bd4-be33-bbb6859b0540",
        wall_time_ns=lambda: 30,
    )
    trail.record(_run())
    uploader = ValidationTelemetryUploadWorker(
        trail,
        _RecordingClient(),
        client_installation_id=UUID("c03732ad-c781-4364-9d3a-c3ce3ea8488c"),
    )
    background = AutomaticValidationTelemetryWorker(uploader, interval_seconds=0.01)

    started_at = time.monotonic()
    background.start()
    start_elapsed = time.monotonic() - started_at
    try:
        deadline = time.monotonic() + 1.0
        while (
            store.telemetry_event_state("a02694ec-c62f-4bd4-be33-bbb6859b0540")
            != ("ACKNOWLEDGED", 0)
            and time.monotonic() < deadline
        ):
            time.sleep(0.01)
    finally:
        background.stop()

    assert start_elapsed < 0.1
    assert store.telemetry_event_state("a02694ec-c62f-4bd4-be33-bbb6859b0540") == (
        "ACKNOWLEDGED",
        0,
    )


def test_retry_delay_backs_off_and_caps_then_resets() -> None:
    assert validation_telemetry_retry_delay(30.0, consecutive_failures=0) == 30.0
    assert validation_telemetry_retry_delay(30.0, consecutive_failures=1) == 30.0
    assert validation_telemetry_retry_delay(30.0, consecutive_failures=2) == 60.0
    assert validation_telemetry_retry_delay(30.0, consecutive_failures=8) == 300.0
