"""Client-owned lifecycle for one server-authorized hardware lease."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Callable, Protocol
from uuid import UUID

from shared.contracts.access_control import HardwareLeaseRequest, HardwareLeaseResponse

from .access_client import CloudAccessError
from .runtime import AuthenticatedInstitutionSession


class LeaseStatus(StrEnum):
    INACTIVE = "INACTIVE"
    ACTIVE = "ACTIVE"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    RELEASED = "RELEASED"


@dataclass(frozen=True, slots=True)
class LeaseState:
    status: LeaseStatus
    lease_id: UUID | None = None
    expires_at: datetime | None = None


class HardwareLeaseClientPort(Protocol):
    def acquire_hardware_lease(
        self, access_token: str, request: HardwareLeaseRequest
    ) -> HardwareLeaseResponse: ...

    def renew_hardware_lease(
        self, access_token: str, lease_id: UUID
    ) -> HardwareLeaseResponse: ...

    def release_hardware_lease(self, access_token: str, lease_id: UUID) -> None: ...


class HardwareLeaseResponseMismatch(RuntimeError):
    """The service returned a lease for a different authenticated binding."""


class HardwareLeaseLifecycle:
    """Acquire and release the server lease without granting local authority."""

    _RENEW_EARLY = timedelta(minutes=2)

    def __init__(
        self,
        client: HardwareLeaseClientPort,
        session: AuthenticatedInstitutionSession,
        access_token: Callable[[], str],
        *,
        now: Callable[[], datetime],
    ) -> None:
        self._client = client
        self._session = session
        self._access_token = access_token
        self._now = now
        self._state = LeaseState(LeaseStatus.INACTIVE)

    @property
    def state(self) -> LeaseState:
        return self._state

    @property
    def allows_new_session(self) -> bool:
        return self._state.status is LeaseStatus.ACTIVE

    @property
    def allows_current_session(self) -> bool:
        return self._state.status in {
            LeaseStatus.ACTIVE,
            LeaseStatus.RECOVERY_REQUIRED,
        }

    def acquire(self) -> LeaseState:
        if self._state.status is LeaseStatus.ACTIVE:
            return self._state
        response = self._client.acquire_hardware_lease(
            self._access_token(),
            HardwareLeaseRequest(
                hardware_id=self._session.hardware_id,
                client_installation_id=UUID(self._session.client_installation_id),
            ),
        )
        self._state = self._validated_active_state(response)
        return self._state

    def renew_if_due(self, now: datetime | None = None) -> LeaseStatus:
        state = self._state
        if state.status is not LeaseStatus.ACTIVE or state.expires_at is None:
            return state.status
        observed_at = now or self._now()
        if observed_at < state.expires_at - self._RENEW_EARLY:
            return LeaseStatus.ACTIVE
        try:
            response = self._client.renew_hardware_lease(
                self._access_token(),
                state.lease_id,
            )
            self._state = self._validated_active_state(response)
        except (CloudAccessError, HardwareLeaseResponseMismatch):
            self._state = LeaseState(LeaseStatus.RECOVERY_REQUIRED, state.lease_id, state.expires_at)
        return self._state.status

    def release(self, reason: str) -> None:
        if not reason:
            raise ValueError("lease release reason is required")
        state = self._state
        if state.lease_id is None or state.status is LeaseStatus.RELEASED:
            return
        try:
            self._client.release_hardware_lease(self._access_token(), state.lease_id)
        except CloudAccessError:
            self._state = LeaseState(LeaseStatus.RECOVERY_REQUIRED, state.lease_id, state.expires_at)
            return
        self._state = LeaseState(LeaseStatus.RELEASED, state.lease_id, state.expires_at)

    def _validated_active_state(self, response: HardwareLeaseResponse) -> LeaseState:
        if (
            response.hardware_id != self._session.hardware_id
            or response.client_installation_id != UUID(self._session.client_installation_id)
        ):
            raise HardwareLeaseResponseMismatch("hardware lease binding does not match")
        return LeaseState(LeaseStatus.ACTIVE, response.lease_id, response.expires_at)


__all__ = [
    "HardwareLeaseLifecycle",
    "HardwareLeaseResponseMismatch",
    "LeaseState",
    "LeaseStatus",
]
