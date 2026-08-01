"""Provider identities, role bindings, masked views, and sensitive access grants."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
from uuid import UUID, uuid4

from cloud.api.access_auth import (
    PlatformAccessContext,
    PlatformAccessTokenIssuer,
    RefreshTokenFactory,
)
from cloud.api.errors import PlatformError
from shared.contracts.access_control import (
    MaskedTenantSummary,
    PlatformLoginRequest,
    PlatformLoginResponse,
    PlatformRole,
    SensitiveAccessGrantRequest,
    SensitiveAccessGrantResponse,
    SensitiveIdentityResponse,
)

from .passwords import hash_password, verify_password
from .platform_service import normalize_login_name
from .repository import (
    AccessRepositoryConflict,
    AuditEventRecord,
    AccessRepository,
    PlatformIdentityRecord,
    PlatformRoleBindingRecord,
    SensitiveAccessGrantRecord,
)


class PlatformPermissionDenied(PlatformError):
    """A Platform role, grant, or token lifetime does not authorize an action."""

    code = "E-PLT-403"
    http_status = 403
    action = "CONTACT_PLATFORM_OWNER"


class PlatformIdentityService:
    _ACCESS_TTL = timedelta(minutes=15)

    def __init__(
        self,
        repository: AccessRepository,
        *,
        login_lookup_hmac_key: bytes,
        token_issuer: PlatformAccessTokenIssuer,
        refresh_tokens: RefreshTokenFactory,
        now=None,
    ) -> None:
        if len(login_lookup_hmac_key) < 32:
            raise ValueError("platform login lookup key must contain at least 32 bytes")
        self._repository = repository
        self._login_lookup_hmac_key = login_lookup_hmac_key
        self._token_issuer = token_issuer
        self._refresh_tokens = refresh_tokens
        self._now = now or (lambda: datetime.now(UTC))

    def _login_digest(self, login_name: str) -> bytes:
        return hmac.new(
            self._login_lookup_hmac_key,
            normalize_login_name(login_name).encode("utf-8"),
            hashlib.sha256,
        ).digest()

    async def bootstrap_owner(
        self,
        *,
        login_name: str,
        display_name: str,
        password: str,
    ) -> PlatformLoginResponse:
        if await self._repository.platform_identity_count() != 0:
            raise RuntimeError("Platform owner bootstrap has already been completed")
        return await self._create_identity(
            login_name=login_name,
            display_name=display_name,
            password=password,
            roles=(PlatformRole.OWNER,),
            actor_id=None,
        )

    async def create_identity(
        self,
        context: PlatformAccessContext,
        *,
        login_name: str,
        display_name: str,
        password: str,
        roles: tuple[PlatformRole, ...],
    ) -> PlatformLoginResponse:
        self._require_active_context(context)
        if PlatformRole.OWNER not in context.roles:
            raise PlatformPermissionDenied("only Platform owner can create identities")
        return await self._create_identity(
            login_name=login_name,
            display_name=display_name,
            password=password,
            roles=roles,
            actor_id=context.platform_identity_id,
        )

    async def _create_identity(
        self,
        *,
        login_name: str,
        display_name: str,
        password: str,
        roles: tuple[PlatformRole, ...],
        actor_id: UUID | None,
    ) -> PlatformLoginResponse:
        now = self._now()
        if not display_name.strip():
            raise ValueError("Platform display name is required")
        if not roles or len(set(roles)) != len(roles):
            raise ValueError("Platform roles must be non-empty and unique")
        identity = PlatformIdentityRecord(
            platform_identity_id=uuid4(),
            login_name_hmac=self._login_digest(login_name),
            display_name=display_name.strip(),
            password_hash=hash_password(password),
            status="ACTIVE",
            token_version=1,
            created_at=now,
        )
        bindings = tuple(
            PlatformRoleBindingRecord(
                binding_id=uuid4(),
                platform_identity_id=identity.platform_identity_id,
                role=role,
                valid_from=now,
            )
            for role in roles
        )
        await self._repository.create_platform_identity(identity, bindings)
        if actor_id is not None:
            await self._repository.append_audit(
                AuditEventRecord(
                    event_id=uuid4(),
                    actor_id=actor_id,
                    action="platform-identity.create",
                    tenant_id=None,
                    resource_id=identity.platform_identity_id,
                    occurred_at=now,
                    details=tuple(("role", role.value) for role in sorted(roles, key=lambda r: r.value)),
                )
            )
        return self._login_response(identity, roles, now=now)

    async def login(self, request: PlatformLoginRequest) -> PlatformLoginResponse:
        now = self._now()
        identity = await self._repository.platform_identity_by_login_hmac(
            self._login_digest(request.login_name)
        )
        if (
            identity is None
            or identity.status != "ACTIVE"
            or not verify_password(request.password, identity.password_hash)
        ):
            raise PlatformPermissionDenied("Platform credentials were rejected")
        roles = await self._repository.platform_roles(
            identity.platform_identity_id,
            at=now,
        )
        if not roles:
            raise PlatformPermissionDenied("Platform identity has no active role")
        return self._login_response(identity, roles, now=now)

    def _login_response(
        self,
        identity: PlatformIdentityRecord,
        roles: tuple[PlatformRole, ...],
        *,
        now: datetime,
    ) -> PlatformLoginResponse:
        access_token = self._token_issuer.issue(
            platform_identity_id=identity.platform_identity_id,
            roles=roles,
            token_version=identity.token_version,
            now=now,
        )
        refresh = self._refresh_tokens.issue()
        return PlatformLoginResponse(
            platform_identity_id=identity.platform_identity_id,
            roles=roles,
            access_token=access_token,
            access_token_expires_at=now + self._ACCESS_TTL,
            refresh_token=refresh.raw_token,
        )

    def verify_access_token(self, token: str) -> PlatformAccessContext:
        return self._token_issuer.verify(token, now=self._now())

    def _require_active_context(self, context: PlatformAccessContext) -> None:
        if context.expires_at <= self._now():
            raise PlatformPermissionDenied("Platform access token is expired")


class SensitiveAccessService:
    _DISCLOSE_ROLES = frozenset({PlatformRole.OWNER, PlatformRole.SUPPORT})

    def __init__(self, repository: AccessRepository, *, now=None) -> None:
        self._repository = repository
        self._now = now or (lambda: datetime.now(UTC))

    def _require_context(self, context: PlatformAccessContext) -> None:
        if context.expires_at <= self._now() or not context.roles:
            raise PlatformPermissionDenied("Platform context is not active")

    async def list_tenants(
        self,
        context: PlatformAccessContext,
    ) -> tuple[MaskedTenantSummary, ...]:
        self._require_context(context)
        rows: list[MaskedTenantSummary] = []
        for tenant in await self._repository.list_tenants():
            account_count, license_count = await self._repository.tenant_access_counts(
                tenant.tenant_id
            )
            rows.append(
                MaskedTenantSummary(
                    tenant_id=tenant.tenant_id,
                    display_name=tenant.name,
                    active_account_count=account_count,
                    active_license_count=license_count,
                )
            )
        return tuple(rows)

    async def issue_grant(
        self,
        context: PlatformAccessContext,
        request: SensitiveAccessGrantRequest,
    ) -> SensitiveAccessGrantResponse:
        self._require_context(context)
        if not context.roles.intersection(self._DISCLOSE_ROLES):
            raise PlatformPermissionDenied("Platform role cannot disclose sensitive identity")
        now = self._now()
        record = SensitiveAccessGrantRecord(
            grant_id=uuid4(),
            tenant_id=request.tenant_id,
            platform_identity_id=context.platform_identity_id,
            purpose_code=request.purpose_code,
            ticket_reference=request.ticket_reference,
            issued_at=now,
            expires_at=now + timedelta(minutes=request.requested_duration_minutes),
        )
        await self._repository.create_sensitive_grant(record)
        await self._repository.append_audit(
            AuditEventRecord(
                event_id=uuid4(),
                actor_id=context.platform_identity_id,
                action="sensitive-access.grant",
                tenant_id=request.tenant_id,
                resource_id=record.grant_id,
                occurred_at=now,
                details=(
                    ("purpose_code", request.purpose_code),
                    ("ticket_reference", request.ticket_reference),
                ),
            )
        )
        return SensitiveAccessGrantResponse(
            grant_id=record.grant_id,
            tenant_id=record.tenant_id,
            purpose_code=record.purpose_code,
            ticket_reference=record.ticket_reference,
            issued_at=record.issued_at,
            expires_at=record.expires_at,
        )

    async def read_identity(
        self,
        context: PlatformAccessContext,
        *,
        grant_id: UUID,
        tenant_id: UUID,
        subject_id: UUID,
        identity_loader: Callable[[], tuple[str | None, str | None]],
    ) -> SensitiveIdentityResponse:
        self._require_context(context)
        if not context.roles.intersection(self._DISCLOSE_ROLES):
            raise PlatformPermissionDenied("Platform role cannot disclose sensitive identity")
        now = self._now()
        try:
            grant = await self._repository.use_sensitive_grant(
                grant_id=grant_id,
                tenant_id=tenant_id,
                platform_identity_id=context.platform_identity_id,
                used_at=now,
            )
        except AccessRepositoryConflict as exc:
            raise PlatformPermissionDenied("sensitive access grant is invalid") from exc
        display_name, contact = identity_loader()
        response = SensitiveIdentityResponse(
            grant_id=grant.grant_id,
            tenant_id=tenant_id,
            subject_id=subject_id,
            display_name=display_name,
            contact=contact,
            disclosed_at=now,
        )
        await self._repository.append_audit(
            AuditEventRecord(
                event_id=uuid4(),
                actor_id=context.platform_identity_id,
                action="sensitive-access.use",
                tenant_id=tenant_id,
                resource_id=subject_id,
                occurred_at=now,
                details=(
                    ("grant_id", str(grant_id)),
                    ("purpose_code", grant.purpose_code),
                    ("ticket_reference", grant.ticket_reference),
                ),
            )
        )
        return response


__all__ = [
    "PlatformIdentityService",
    "PlatformPermissionDenied",
    "SensitiveAccessService",
]
