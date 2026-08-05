from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from client.cloud.access_client import AccessAuthenticationFailed
from client.cloud.access_store import ClientAccessStore
from client.cloud.hardware_identity import (
    ActivationHardwareResult,
    ActivationHardwareStatus,
)
from client.cloud.policy import AccountHardwareLicenseVerifier
from client.cloud.runtime import ClientAccessRuntime, ClientAccessRuntimeError
from client.support import (
    SafeClientEventName,
    SafeClientEventOutcome,
    SafeClientEventRecorder,
    SafeClientEventStore,
)
from shared.contracts.access_control import (
    ActivateAccountResponse,
    LicenseDocumentV2,
    LoginResponse,
    RefreshResponse,
)
from shared.contracts.client_sync import canonical_json_bytes


class _MemoryCredentials:
    def __init__(self) -> None:
        self.values: dict[UUID, str] = {}

    def set_refresh_token(self, account_id: UUID, refresh_token: str) -> None:
        self.values[account_id] = refresh_token

    def get_refresh_token(self, account_id: UUID) -> str | None:
        return self.values.get(account_id)

    def delete_refresh_token(self, account_id: UUID) -> None:
        self.values.pop(account_id, None)


class _FixedHardware:
    def discover(self) -> ActivationHardwareResult:
        return ActivationHardwareResult(ActivationHardwareStatus.READY)


class _FakeAccessClient:
    def __init__(self, now: datetime, hardware_id: str) -> None:
        self.now = now
        self.last_server_time = now
        self.hardware_id = hardware_id
        self.tenant_id = uuid4()
        self.account_id = uuid4()
        self.license_id = uuid4()
        self.hardware_asset_id = uuid4()
        self.private_key = Ed25519PrivateKey.generate()
        self.password_canary = "PW-CANARY-96-value-long"
        self.activation_canary = "ACT-CANARY-96-value-long"
        self.refresh_canary = "REFRESH-CANARY-96-value-long"
        self.access_canary = "ACCESS-CANARY-96-value-long"
        self.signed_license_canary = "LICENSE-CANARY-96"
        self.private_key_canary = "PRIVATE-KEY-CANARY-96"
        self.patient_canary = "PATIENT-CANARY-96"
        self.record_number_canary = "MRN-CANARY-96"
        self.contact_canary = "CONTACT-CANARY-96"
        public_key = self.private_key.public_key().public_bytes(
            Encoding.Raw,
            PublicFormat.Raw,
        )
        self.verifier = AccountHardwareLicenseVerifier({"license/2-key-1": public_key})
        self.reject_login = False

    def _data(self, installation_id: UUID) -> dict[str, object]:
        document = LicenseDocumentV2.model_validate(
            {
                "tenant_id": self.tenant_id,
                "account_id": self.account_id,
                "license_id": self.license_id,
                "hardware_id": self.hardware_id,
                "status": "ACTIVE",
                "issued_at": self.now,
                "valid_from": self.now,
                "valid_until": self.now + timedelta(days=365),
                "version": 1,
                "enabled_features": ["reports.view", "screening.start", "sync.upload"],
            }
        )
        signature = base64.b64encode(
            self.private_key.sign(canonical_json_bytes(document))
        ).decode("ascii")
        return {
            "tenant_id": self.tenant_id,
            "account_id": self.account_id,
            "license_id": self.license_id,
            "hardware_asset_id": self.hardware_asset_id,
            "hardware_id": self.hardware_id,
            "client_installation_id": installation_id,
            "access_token": self.access_canary,
            "access_token_expires_at": self.now + timedelta(minutes=15),
            "refresh_token": self.refresh_canary,
            "refresh_idle_expires_at": self.now + timedelta(days=30),
            "refresh_absolute_expires_at": self.now + timedelta(days=180),
            "signed_license": {
                "document": document.model_dump(mode="json"),
                "key_id": "license/2-key-1",
                "signature": signature,
            },
            "capabilities": {
                "allow_new_test": True,
                "allow_upload": True,
                "allow_report_view": True,
            },
        }

    def activate(self, request):
        return ActivateAccountResponse.model_validate(
            {**self._data(request.client_installation_id), "account_state": "ACTIVE"}
        )

    def login(self, request):
        if self.reject_login:
            raise AccessAuthenticationFailed("login rejected", status_code=401)
        return LoginResponse.model_validate(
            {**self._data(request.client_installation_id), "account_state": "ACTIVE"}
        )

    def refresh(self, request):
        return RefreshResponse.model_validate(self._data(request.client_installation_id))

    def logout(self, request) -> None:
        _ = request


def _runtime(tmp_path: Path, events: object | None = None) -> tuple[ClientAccessRuntime, _FakeAccessClient, ClientAccessStore]:
    now = datetime(2026, 8, 2, 20, 30, tzinfo=UTC)
    hardware_id = "FFP-DP4864-000001"
    client = _FakeAccessClient(now, hardware_id)
    store = ClientAccessStore(tmp_path / "access.sqlite3", _MemoryCredentials())
    runtime = ClientAccessRuntime(
        client,
        store,
        _FixedHardware(),
        license_verifier=client.verifier,
        client_installation_id=uuid4(),
        now=lambda: now,
        monotonic_ns=lambda: 100,
        events=events,
    )
    return runtime, client, store


def _recorder(tmp_path: Path) -> SafeClientEventRecorder:
    return SafeClientEventRecorder(
        SafeClientEventStore(tmp_path / "safe-events"),
        client_installation_id=UUID("8be74f4c-916b-4e6b-b78e-f53e7f7b5475"),
        app_version="0.1.0",
        protocol_version="do-p4864-observed-compact-8bit/1",
        data_mode_version="48x64-uint8-column-major/1",
        config_version="client-support/1",
        now=lambda: datetime(2026, 8, 2, 20, 30, tzinfo=UTC),
    )


def test_actual_authentication_flows_write_only_closed_safe_events(tmp_path: Path) -> None:
    """Removing an auth event or forwarding a secret must fail this real JSONL flow."""
    recorder = _recorder(tmp_path)
    runtime, client, store = _runtime(tmp_path, recorder)
    try:
        runtime.activate(
            "seed-clinic",
            client.activation_canary,
            client.password_canary,
            client.password_canary,
            client.hardware_id,
        )
        runtime.login("seed-clinic", client.password_canary)
        runtime.refresh()
    finally:
        store.close()

    records = SafeClientEventStore(tmp_path / "safe-events").verified_records()
    assert [(record.event.name, record.event.outcome, record.event.error_code) for record in records] == [
        (SafeClientEventName.AUTH_ACTIVATION_ACCEPTED, SafeClientEventOutcome.OK, None),
        (SafeClientEventName.AUTH_LOGIN_ACCEPTED, SafeClientEventOutcome.OK, None),
        (SafeClientEventName.AUTH_REFRESH_ACCEPTED, SafeClientEventOutcome.OK, None),
    ]
    serialized = (tmp_path / "safe-events" / "events.jsonl").read_text(encoding="utf-8")
    for canary in (
        client.password_canary,
        client.activation_canary,
        client.refresh_canary,
        client.access_canary,
        client.signed_license_canary,
        client.private_key_canary,
        client.patient_canary,
        client.record_number_canary,
        client.contact_canary,
        "password",
        "activation_code",
        "refresh_token",
        "access_token",
        "signed_license",
        "private_key",
        "patient_name",
        "record_number",
        "contact",
    ):
        assert canary not in serialized


def test_rejected_login_records_stable_event_without_changing_public_error(tmp_path: Path) -> None:
    """Replacing the stable auth rejection mapping must fail the public-flow record."""
    recorder = _recorder(tmp_path)
    runtime, client, store = _runtime(tmp_path, recorder)
    client.reject_login = True
    try:
        with pytest.raises(AccessAuthenticationFailed, match="login rejected"):
            runtime.login("seed-clinic", client.password_canary)
    finally:
        store.close()

    event = SafeClientEventStore(tmp_path / "safe-events").verified_records()[0].event
    assert (event.name, event.outcome, event.error_code) == (
        SafeClientEventName.AUTH_LOGIN_REJECTED,
        SafeClientEventOutcome.REJECTED,
        "E-AUT-001",
    )


def test_access_runtime_closes_its_owned_access_store(tmp_path: Path) -> None:
    """Removing formal shutdown ownership must leave the packaged SQLite connection open."""
    runtime, _client, store = _runtime(tmp_path)

    runtime.close()

    with pytest.raises(Exception):
        store.load()


def test_access_runtime_closes_store_after_cloud_close_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cloud-close failure must not leave the owned access SQLite connection open."""
    runtime, client, store = _runtime(tmp_path)
    order: list[str] = []

    def fail_cloud_close() -> None:
        order.append("cloud")
        raise RuntimeError("close failure")

    client.close = fail_cloud_close
    monkeypatch.setattr(store, "close", lambda: order.append("store"))

    with pytest.raises(RuntimeError, match="close failure"):
        runtime.close()

    assert order == ["cloud", "store"]


class _FalseRecorder:
    def record(self, *args, **kwargs) -> bool:
        _ = args, kwargs
        return False


class _ExplodingRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[object, object, object | None]] = []

    def record(self, *args, **kwargs) -> bool:
        self.calls.append((args[0], args[1], kwargs.get("error_code")))
        raise RuntimeError("event recorder failure")


def test_recorder_failures_do_not_change_login_results_or_errors(tmp_path: Path) -> None:
    """Letting a recorder failure escape would break auth despite an optional diagnostic."""
    successful, _, successful_store = _runtime(tmp_path / "successful", _FalseRecorder())
    rejected, rejected_client, rejected_store = _runtime(tmp_path / "rejected", _ExplodingRecorder())
    rejected_client.reject_login = True
    try:
        assert successful.login("seed-clinic", "PW-CANARY-96-value-long").access_token == "ACCESS-CANARY-96-value-long"
        with pytest.raises(AccessAuthenticationFailed, match="login rejected"):
            rejected.login("seed-clinic", "PW-CANARY-96-value-long")
    finally:
        successful_store.close()
        rejected_store.close()


def test_refresh_session_acceptance_rejection_records_once_and_preserves_error(
    tmp_path: Path,
) -> None:
    """Dropping a post-response rejection event must fail this real safe-store flow."""
    recorder = _recorder(tmp_path)
    runtime, client, store = _runtime(tmp_path, recorder)
    try:
        runtime.login("seed-clinic", client.password_canary)
        client.last_server_time = None
        with pytest.raises(ClientAccessRuntimeError, match="机构服务未返回可信时间"):
            runtime.refresh()
    finally:
        store.close()

    records = SafeClientEventStore(tmp_path / "safe-events").verified_records()
    assert [(record.event.name, record.event.outcome, record.event.error_code) for record in records] == [
        (SafeClientEventName.AUTH_LOGIN_ACCEPTED, SafeClientEventOutcome.OK, None),
        (
            SafeClientEventName.AUTH_REFRESH_REJECTED,
            SafeClientEventOutcome.REJECTED,
            "E-AUT-001",
        ),
    ]


def test_refresh_session_acceptance_rejection_ignores_exploding_recorder(
    tmp_path: Path,
) -> None:
    """A post-response recorder failure must not replace the existing runtime error."""
    recorder = _ExplodingRecorder()
    runtime, client, store = _runtime(tmp_path, recorder)
    try:
        runtime.login("seed-clinic", client.password_canary)
        recorder.calls.clear()
        client.last_server_time = None
        with pytest.raises(ClientAccessRuntimeError, match="机构服务未返回可信时间"):
            runtime.refresh()
    finally:
        store.close()

    assert recorder.calls == [
        (
            SafeClientEventName.AUTH_REFRESH_REJECTED,
            SafeClientEventOutcome.REJECTED,
            "E-AUT-001",
        )
    ]
