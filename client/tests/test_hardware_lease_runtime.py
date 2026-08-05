from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from client.cloud.access_client import AccessConflict
from client.cloud.lease_runtime import HardwareLeaseLifecycle, LeaseStatus
from client.cloud.runtime import AuthenticatedInstitutionSession
from shared.contracts.access_control import HardwareLeaseResponse


class _LeaseClient:
    def __init__(self, now: datetime) -> None:
        self.now = now
        self.requests = []
        self.renew_error: Exception | None = None
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
        return HardwareLeaseResponse(
            lease_id=lease_id,
            hardware_id="FFP-DP4864-000001",
            client_installation_id=uuid4(),
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
