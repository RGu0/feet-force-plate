from __future__ import annotations

from datetime import UTC, datetime, timedelta
import threading
from uuid import UUID, uuid4

import pytest

from client.cloud.access_client import AccessConflict, AccessServiceUnavailable
from client.cloud.lease_runtime import HardwareLeaseLifecycle, HardwareLeaseUnavailable, LeaseStatus
from client.cloud.runtime import AuthenticatedInstitutionSession
from techflex_cloud_foundation.contracts.access_control import HardwareLeaseResponse


class _LeaseClient:
    def __init__(self, now: datetime) -> None:
        self.now = now
        self.requests = []
        self.renew_error: Exception | None = None
        self.renewed = threading.Event()
        self.released: list[UUID] = []
        self.lease_id = uuid4()

    def acquire_hardware_lease(self, access_token, request):
        self.requests.append((access_token, request))
        return HardwareLeaseResponse(
            lease_id=self.lease_id,
            hardware_id=request.hardware_id,
            client_installation_id=request.client_installation_id,
            acquired_at=self.now,
            expires_at=self.now + timedelta(minutes=10),
        )

    def renew_hardware_lease(self, _access_token, lease_id):
        if self.renew_error is not None:
            raise self.renew_error
        self.renewed.set()
        return HardwareLeaseResponse(
            lease_id=lease_id,
            hardware_id="FFP-DP4864-000001",
            client_installation_id=self.requests[-1][1].client_installation_id,
            acquired_at=self.now,
            expires_at=self.now + timedelta(minutes=10),
        )

    def release_hardware_lease(self, _access_token, lease_id):
        self.released.append(lease_id)


def _session() -> AuthenticatedInstitutionSession:
    return AuthenticatedInstitutionSession(
        tenant_id=str(uuid4()),
        account_id=str(uuid4()),
        license_id=str(uuid4()),
        hardware_asset_id=str(uuid4()),
        hardware_id="FFP-DP4864-000001",
        client_installation_id=str(uuid4()),
        access_token="access-token-value-at-least-20",
        signed_license="signed-license",
    )


def test_acquire_uses_server_hardware_identity_not_internal_asset_uuid() -> None:
    now = datetime(2026, 8, 5, 8, 0, tzinfo=UTC)
    client = _LeaseClient(now)
    session = _session()

    state = HardwareLeaseLifecycle(client, session, lambda: session.access_token, now=lambda: now).acquire()

    assert state.status is LeaseStatus.ACTIVE
    _token, request = client.requests[-1]
    assert request.hardware_id == session.hardware_id
    assert request.hardware_id != session.hardware_asset_id
    assert request.client_installation_id == UUID(session.client_installation_id)


def test_renewal_conflict_keeps_current_capture_allowed_but_blocks_next_one() -> None:
    now = datetime(2026, 8, 5, 8, 0, tzinfo=UTC)
    client = _LeaseClient(now)
    session = _session()
    lifecycle = HardwareLeaseLifecycle(client, session, lambda: session.access_token, now=lambda: now)
    lifecycle.acquire()
    client.renew_error = AccessConflict("conflict", status_code=409)

    assert lifecycle.renew_if_due(now + timedelta(minutes=9, seconds=1)) is LeaseStatus.RECOVERY_REQUIRED
    assert lifecycle.allows_current_session is True
    assert lifecycle.allows_new_session is False


def test_release_is_idempotent_after_successful_acquisition() -> None:
    now = datetime(2026, 8, 5, 8, 0, tzinfo=UTC)
    client = _LeaseClient(now)
    session = _session()
    lifecycle = HardwareLeaseLifecycle(client, session, lambda: session.access_token, now=lambda: now)
    lifecycle.acquire()

    lifecycle.release("CAPTURE_FINISHED")
    lifecycle.release("APPLICATION_CLOSED")

    assert client.released == [client.lease_id]
    assert lifecycle.state.status is LeaseStatus.RELEASED


def test_active_capture_renews_in_background_and_joins_before_release(monkeypatch) -> None:
    client = _LeaseClient(datetime(2026, 8, 5, tzinfo=UTC))
    session = _session()
    lifecycle = HardwareLeaseLifecycle(client, session, lambda: session.access_token,
                                       now=lambda: client.now)
    monkeypatch.setattr(lifecycle, "_HEARTBEAT_INTERVAL_SECONDS", 0.01)
    lifecycle.acquire()
    lifecycle.start_capture()
    try:
        client.now += timedelta(minutes=9)
        assert client.renewed.wait(3)
    finally:
        lifecycle.release("CAPTURE_ENDED")
    assert lifecycle.state.expires_at == client.now + timedelta(minutes=10)
    assert lifecycle.state.status is LeaseStatus.RELEASED
    assert client.released == [client.lease_id]


def test_expired_preflight_lease_is_reacquired_before_capture() -> None:
    client = _LeaseClient(datetime(2026, 8, 5, tzinfo=UTC))
    session = _session()
    lifecycle = HardwareLeaseLifecycle(client, session, lambda: session.access_token,
                                       now=lambda: client.now)
    lifecycle.acquire()
    client.now += timedelta(minutes=10)
    assert not lifecycle.allows_new_session
    lifecycle.start_capture()
    try:
        assert len(client.requests) == 2
        assert lifecycle.allows_new_session
    finally:
        lifecycle.release("CAPTURE_ENDED")


def test_transient_renewal_retries_only_the_original_unexpired_lease() -> None:
    client = _LeaseClient(datetime(2026, 8, 5, tzinfo=UTC))
    session = _session()
    lifecycle = HardwareLeaseLifecycle(client, session, lambda: session.access_token,
                                       now=lambda: client.now)
    original = lifecycle.acquire()
    client.now += timedelta(minutes=9)
    client.renew_error = AccessServiceUnavailable("temporarily offline")
    assert lifecycle.renew_if_due() is LeaseStatus.RETRYING
    assert lifecycle.allows_current_session and not lifecycle.allows_new_session
    client.renew_error = None
    assert lifecycle.renew_if_due() is LeaseStatus.ACTIVE
    assert lifecycle.state.lease_id == original.lease_id
    client.now += timedelta(minutes=10)
    client.renewed.clear()
    assert lifecycle.renew_if_due() is LeaseStatus.RECOVERY_REQUIRED
    assert not client.renewed.is_set()


def test_end_capture_returns_while_release_is_in_flight(monkeypatch) -> None:
    client = _LeaseClient(datetime(2026, 8, 5, tzinfo=UTC))
    session = _session()
    lifecycle = HardwareLeaseLifecycle(client, session, lambda: session.access_token,
                                       now=lambda: client.now)
    started, finish = threading.Event(), threading.Event()

    def slow_release(_token, _lease_id):
        started.set()
        assert finish.wait(3)

    monkeypatch.setattr(client, "release_hardware_lease", slow_release)
    lifecycle.start_capture()
    try:
        lifecycle.end_capture()
        assert started.wait(3)
        assert lifecycle.state.status is LeaseStatus.ACTIVE
    finally:
        finish.set()
        lifecycle.release("APPLICATION_CLOSED")
    assert lifecycle.state.status is LeaseStatus.RELEASED


def test_unknown_release_never_admits_an_id_that_a_late_delete_can_close(monkeypatch) -> None:
    client = _LeaseClient(datetime(2026, 8, 5, tzinfo=UTC))
    session = _session()
    lifecycle = HardwareLeaseLifecycle(client, session, lambda: session.access_token,
                                       now=lambda: client.now)

    def timeout(*_args):
        raise AccessServiceUnavailable("release response timed out")

    monkeypatch.setattr(client, "release_hardware_lease", timeout)
    lifecycle.start_capture()
    lifecycle.release("CAPTURE_ENDED")
    with pytest.raises(HardwareLeaseUnavailable):
        lifecycle.start_capture()
    assert not lifecycle.allows_new_session
    client.lease_id = uuid4()
    lifecycle.start_capture()
    try:
        assert lifecycle.allows_new_session
    finally:
        lifecycle.release("CAPTURE_ENDED")
