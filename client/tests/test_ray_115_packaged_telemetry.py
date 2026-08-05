from __future__ import annotations

from pathlib import Path
import time

from client.app.packaged_entry import start_default_validation_telemetry_upload
from client.spool.state_store import SensitiveBlobCodec, StateStore
from client.startup_validation.telemetry_upload import ValidationTelemetryCloudClient
from client.startup_validation.models import (
    DeviceValidationRun,
    ValidationOutcome,
    ValidationReason,
)
from client.startup_validation.persistence import ValidationAuditTrail


class _Keys:
    def get_key(self) -> bytes:
        return b"p" * 32


class _CloudClient:
    def __init__(self) -> None:
        self.closed = False

    def upload(self, request):
        return tuple(event.event_id for event in request.events)

    def close(self) -> None:
        self.closed = True


def test_validation_telemetry_client_ignores_ambient_socks_proxy(monkeypatch) -> None:
    monkeypatch.setenv("ALL_PROXY", "socks5://127.0.0.1:1080")

    client = ValidationTelemetryCloudClient(
        "https://seed.invalid",
        access_token_provider=lambda: "unused-token",
    )

    client.close()


def test_packaged_authenticated_composition_starts_and_stops_background_upload(
    tmp_path: Path,
) -> None:
    store = StateStore(
        tmp_path / "state.sqlite3",
        SensitiveBlobCodec(_Keys()),
    )
    trail = ValidationAuditTrail(
        store,
        event_id_factory=lambda: "a02694ec-c62f-4bd4-be33-bbb6859b0540",
        wall_time_ns=lambda: 30,
    )
    trail.record(
        DeviceValidationRun(
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
        )
    )
    cloud = _CloudClient()

    runtime = start_default_validation_telemetry_upload(
        audit_trail=trail,
        cloud_client=cloud,
        client_installation_id="c03732ad-c781-4364-9d3a-c3ce3ea8488c",
        interval_seconds=0.01,
    )
    try:
        deadline = time.monotonic() + 1.0
        while (
            store.telemetry_event_state("a02694ec-c62f-4bd4-be33-bbb6859b0540")
            != ("ACKNOWLEDGED", 0)
            and time.monotonic() < deadline
        ):
            time.sleep(0.01)
        final_state = store.telemetry_event_state(
            "a02694ec-c62f-4bd4-be33-bbb6859b0540"
        )
    finally:
        runtime.stop()
        store.close()

    assert cloud.closed is True
    assert final_state == ("ACKNOWLEDGED", 0)
