from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, Header, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from cloud.api.auth import TerminalContext, TerminalTokenIssuer
from cloud.api.access_auth import (
    PlatformAccessContext,
    PlatformAccessTokenIssuer,
    TenantAccessContext,
    TenantAccessTokenIssuer,
)
from cloud.api.operations_auth import OperationsTokenIssuer
from cloud.api.errors import (
    AuthenticationError,
    PlatformError,
    RepositoryUnavailable,
    RequestContractError,
    ResourceNotFound,
    TenantAccessDenied,
)
from cloud.ingestion.service import IngestionService
from cloud.ingestion.principal import (
    IngestionPrincipal,
    legacy_terminal_principal,
    tenant_ingestion_principal,
)
from shared.contracts.client_sync import decode_segment_metadata
from shared.contracts.access_control import (
    ActivateAccountRequest,
    HardwareLeaseRequest,
    LicenseControlRequest,
    LoginRequest,
    LogoutRequest,
    PlatformLoginRequest,
    ProvisionTenantRequest,
    RefreshRequest,
    SensitiveAccessGrantRequest,
)
from shared.contracts.cloud import (
    ConsentCreateRequest,
    ConsentRevokeRequest,
    EnrollmentRequest,
    HeartbeatRequest,
    SessionCreateRequest,
    SessionManifest,
    SubjectCreateRequest,
    SubjectResolveRequest,
)
from shared.contracts.operations import (
    ActivationCodeIssueRequest,
    DataAccessRequest,
    DeviceRegistrationRequest,
    LicenseIssueRequest,
    LicenseRenewRequest,
    LicenseRevokeRequest,
    SiteCreateRequest,
    TerminalStatusChangeRequest,
    UpgradePolicyRequest,
    UpgradePolicyStatusRequest,
)
from shared.contracts.validation_telemetry import (
    DeviceValidationTelemetryBatchRequest,
)


@dataclass(frozen=True, slots=True)
class ServiceContainer:
    ingestion: IngestionService | None = None
    token_issuer: TerminalTokenIssuer | None = None
    subjects: object | None = None
    devices: object | None = None
    heartbeats: object | None = None
    operations: object | None = None
    operations_tokens: OperationsTokenIssuer | None = None
    tenant_access: object | None = None
    tenant_tokens: TenantAccessTokenIssuer | None = None
    hardware_leases: object | None = None
    platform_identities: object | None = None
    platform_access: object | None = None
    platform_tokens: PlatformAccessTokenIssuer | None = None
    platform_sensitive: object | None = None
    platform_reports: object | None = None
    platform_subjects: object | None = None
    validation_telemetry: object | None = None


def _meta(request: Request) -> dict[str, str]:
    return {
        "request_id": str(request.state.request_id),
        "correlation_id": str(request.state.correlation_id),
        "server_time": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }


def _data_response(request: Request, data, status_code: int = 200) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=jsonable_encoder({"data": data, "meta": _meta(request)}),
        headers={"X-Correlation-ID": str(request.state.correlation_id)},
    )


def create_app(container: ServiceContainer) -> FastAPI:
    app = FastAPI(
        title="FeetForcePlate Cloud API",
        version="1.0.0",
        description="Institutional screening ingestion API; it does not provide disease diagnosis.",
    )
    app.state.services = container

    @app.middleware("http")
    async def correlation_context(request: Request, call_next):
        request.state.request_id = uuid4()
        raw_correlation = request.headers.get("X-Correlation-ID")
        try:
            request.state.correlation_id = UUID(raw_correlation) if raw_correlation else uuid4()
        except ValueError:
            request.state.correlation_id = uuid4()
            return JSONResponse(
                status_code=400,
                content={
                    "error": {
                        "code": "E-API-400",
                        "message": "X-Correlation-ID 必须是 UUID",
                        "retryable": False,
                        "action": "FIX_REQUEST",
                        "details": {},
                    },
                    "meta": _meta(request),
                },
                headers={"X-Correlation-ID": str(request.state.correlation_id)},
            )
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = str(request.state.correlation_id)
        return response

    @app.exception_handler(PlatformError)
    async def platform_error_handler(request: Request, exc: PlatformError):
        allowed_details = {
            "session_id",
            "segment_index",
            "schema_version",
            "session_schema",
            "segment_schema",
            "expected",
            "actual",
            "missing_or_mismatched",
            "extra",
            "scope",
            "terminal_id",
            "device_id",
            "subject_uuid",
            "validity_status",
            "object_key",
        }
        details = {key: value for key, value in exc.details.items() if key in allowed_details}
        return JSONResponse(
            status_code=exc.http_status,
            content=jsonable_encoder(
                {
                    "error": {
                        "code": exc.code,
                        "message": exc.message,
                        "retryable": exc.retryable,
                        "action": exc.action,
                        "details": details,
                    },
                    "meta": _meta(request),
                }
            ),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        safe_fields = [".".join(str(part) for part in error["loc"]) for error in exc.errors()]
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "E-API-422",
                    "message": "请求字段不符合版本化契约",
                    "retryable": False,
                    "action": "FIX_REQUEST",
                    "details": {"fields": safe_fields},
                },
                "meta": _meta(request),
            },
        )

    def terminal_context(
        authorization: Annotated[str, Header(alias="Authorization")],
        terminal_header_id: Annotated[UUID, Header(alias="X-Terminal-ID")],
    ) -> TerminalContext:
        if container.token_issuer is None:
            raise RepositoryUnavailable("终端身份服务暂不可用")
        scheme, separator, token = authorization.partition(" ")
        if separator != " " or scheme.lower() != "bearer" or not token:
            raise AuthenticationError("缺少有效终端 Bearer 凭据")
        context = container.token_issuer.verify(token)
        if context.terminal_id != terminal_header_id:
            raise TenantAccessDenied(
                "X-Terminal-ID 与终端凭据不一致",
                terminal_id=str(terminal_header_id),
            )
        return context

    def heartbeat_context(
        authorization: Annotated[str, Header(alias="Authorization")],
        terminal_header_id: Annotated[UUID, Header(alias="X-Terminal-ID")],
    ) -> IngestionPrincipal | TerminalContext:
        scheme, separator, token = authorization.partition(" ")
        if separator != " " or scheme.lower() != "bearer" or not token:
            raise AuthenticationError("缺少有效终端 Bearer 凭据")
        if container.tenant_tokens is not None:
            context = tenant_ingestion_principal(container.tenant_tokens.verify(token))
        elif container.token_issuer is not None:
            context = container.token_issuer.verify(token)
        else:
            raise RepositoryUnavailable("终端身份服务暂不可用")
        if context.terminal_id != terminal_header_id:
            raise TenantAccessDenied(
                "X-Terminal-ID 与终端凭据不一致",
                terminal_id=str(terminal_header_id),
            )
        return context

    HeartbeatDependency = Annotated[
        IngestionPrincipal | TerminalContext,
        Depends(heartbeat_context),
    ]

    def operations_context(
        authorization: Annotated[str, Header(alias="Authorization")],
    ):
        if container.operations_tokens is None:
            raise RepositoryUnavailable("运营身份服务暂不可用")
        scheme, separator, token = authorization.partition(" ")
        if separator != " " or scheme.lower() != "bearer" or not token:
            raise AuthenticationError("缺少有效运营 Bearer 凭据")
        return container.operations_tokens.verify(token)

    OperationsDependency = Annotated[object, Depends(operations_context)]

    def tenant_context(
        authorization: Annotated[str, Header(alias="Authorization")],
    ) -> TenantAccessContext:
        if container.tenant_tokens is None:
            raise RepositoryUnavailable("机构身份服务暂不可用")
        scheme, separator, token = authorization.partition(" ")
        if separator != " " or scheme.lower() != "bearer" or not token:
            raise AuthenticationError("缺少有效机构 Bearer 凭据")
        return container.tenant_tokens.verify(token)

    TenantAccessDependency = Annotated[TenantAccessContext, Depends(tenant_context)]

    def data_context(
        authorization: Annotated[str, Header(alias="Authorization")],
        terminal_header_id: Annotated[
            UUID | None,
            Header(alias="X-Terminal-ID"),
        ] = None,
    ) -> IngestionPrincipal:
        scheme, separator, token = authorization.partition(" ")
        if separator != " " or scheme.lower() != "bearer" or not token:
            raise AuthenticationError("缺少有效数据 Bearer 凭据")
        if container.tenant_tokens is not None:
            return tenant_ingestion_principal(container.tenant_tokens.verify(token))
        if container.token_issuer is None:
            raise RepositoryUnavailable("数据身份服务暂不可用")
        if terminal_header_id is None:
            raise AuthenticationError("缺少 X-Terminal-ID")
        terminal = container.token_issuer.verify(token)
        if terminal.terminal_id != terminal_header_id:
            raise TenantAccessDenied(
                "X-Terminal-ID 与终端凭据不一致",
                terminal_id=str(terminal_header_id),
            )
        return legacy_terminal_principal(terminal)

    DataDependency = Annotated[IngestionPrincipal, Depends(data_context)]

    async def platform_context(
        authorization: Annotated[str, Header(alias="Authorization")],
    ) -> PlatformAccessContext:
        if (
            container.platform_identities is None
            or container.platform_tokens is None
        ):
            raise RepositoryUnavailable("平台身份服务暂不可用")
        scheme, separator, token = authorization.partition(" ")
        if separator != " " or scheme.lower() != "bearer" or not token:
            raise AuthenticationError("缺少有效平台 Bearer 凭据")
        return await container.platform_identities.verify_access_token(token)

    PlatformAccessDependency = Annotated[PlatformAccessContext, Depends(platform_context)]

    def source_fingerprint(request: Request) -> bytes:
        host = request.client.host if request.client is not None else "unknown"
        return hashlib.sha256(f"tenant|{host}".encode("utf-8")).digest()

    def _platform_source_fingerprint(request: Request) -> bytes:
        host = request.client.host if request.client is not None else "unknown"
        return hashlib.sha256(f"platform|{host}".encode("utf-8")).digest()

    def operations_service():
        if container.operations is None:
            raise RepositoryUnavailable("运营控制面暂不可用")
        return container.operations

    if container.tenant_access is not None and container.tenant_tokens is not None:

        @app.post("/v1/access/activate")
        async def access_activate(request: Request, body: ActivateAccountRequest):
            result = await container.tenant_access.activate(
                body,
                source_fingerprint=source_fingerprint(request),
            )
            return _data_response(request, result, 201)

        @app.post("/v1/access/login")
        async def access_login(request: Request, body: LoginRequest):
            result = await container.tenant_access.login(
                body,
                source_fingerprint=source_fingerprint(request),
            )
            return _data_response(request, result)

        @app.post("/v1/access/refresh")
        async def access_refresh(request: Request, body: RefreshRequest):
            result = await container.tenant_access.refresh(body)
            return _data_response(request, result)

        @app.post("/v1/access/logout")
        async def access_logout(request: Request, body: LogoutRequest):
            await container.tenant_access.logout(body)
            return _data_response(request, {"logged_out": True})

        @app.get("/v1/access/license")
        async def access_license(
            request: Request,
            context: TenantAccessDependency,
        ):
            result = await container.tenant_access.current_license(context)
            return _data_response(request, result)

    if container.validation_telemetry is not None and container.tenant_tokens is not None:

        @app.post("/v1/telemetry/device-validation")
        async def upload_device_validation_telemetry(
            request: Request,
            body: DeviceValidationTelemetryBatchRequest,
            context: TenantAccessDependency,
        ):
            result = container.validation_telemetry.ingest(context, body)
            return _data_response(request, result, 202)

    if container.hardware_leases is not None and container.tenant_tokens is not None:

        @app.post("/v1/access/hardware-lease")
        async def acquire_hardware_lease(
            request: Request,
            body: HardwareLeaseRequest,
            context: TenantAccessDependency,
        ):
            result = await container.hardware_leases.acquire(context, body)
            return _data_response(request, result, 201)

        @app.put("/v1/access/hardware-lease/{lease_id}")
        async def renew_hardware_lease(
            request: Request,
            lease_id: UUID,
            context: TenantAccessDependency,
        ):
            result = await container.hardware_leases.renew(context, lease_id)
            return _data_response(request, result)

        @app.delete("/v1/access/hardware-lease/{lease_id}")
        async def release_hardware_lease(
            request: Request,
            lease_id: UUID,
            context: TenantAccessDependency,
        ):
            await container.hardware_leases.release(context, lease_id)
            return _data_response(request, {"released": True})

    if container.platform_identities is not None:

        @app.post("/v1/platform/login")
        async def platform_login(request: Request, body: PlatformLoginRequest):
            result = await container.platform_identities.login(
                body,
                source_fingerprint=_platform_source_fingerprint(request),
            )
            return _data_response(request, result)

    if container.platform_access is not None and container.platform_tokens is not None:

        @app.post("/v1/platform/tenants")
        async def platform_create_tenant(
            request: Request,
            body: ProvisionTenantRequest,
            context: PlatformAccessDependency,
        ):
            result = await container.platform_access.provision_tenant(context, body)
            return _data_response(request, result, 201)

        @app.post("/v1/platform/tenants/{tenant_id}/licenses")
        async def platform_add_tenant_license(
            request: Request,
            tenant_id: UUID,
            body: ProvisionTenantRequest,
            context: PlatformAccessDependency,
        ):
            result = await container.platform_access.add_tenant_access_group(
                context,
                tenant_id,
                body,
            )
            return _data_response(request, result, 201)

        @app.patch("/v1/platform/licenses/{license_id}")
        async def platform_control_license(
            request: Request,
            license_id: UUID,
            body: LicenseControlRequest,
            context: PlatformAccessDependency,
        ):
            result = await container.platform_access.control_license(
                context,
                license_id,
                body,
            )
            return _data_response(request, result)

    if container.platform_sensitive is not None and container.platform_tokens is not None:

        @app.get("/v1/platform/tenants")
        async def platform_list_tenants(
            request: Request,
            context: PlatformAccessDependency,
        ):
            result = await container.platform_sensitive.list_tenants(context)
            return _data_response(request, result)

        @app.post("/v1/platform/sensitive-access-grants")
        async def platform_issue_sensitive_grant(
            request: Request,
            body: SensitiveAccessGrantRequest,
            context: PlatformAccessDependency,
        ):
            result = await container.platform_sensitive.issue_grant(context, body)
            return _data_response(request, result, 201)

    if (
        container.platform_reports is not None
        and container.platform_tokens is not None
    ):

        @app.get("/v1/platform/tenants/{tenant_id}/reports")
        async def platform_list_reports(
            request: Request,
            tenant_id: UUID,
            context: PlatformAccessDependency,
        ):
            result = await container.platform_reports.list_masked_reports(
                context,
                tenant_id,
            )
            return _data_response(request, result)

    if (
        container.platform_subjects is not None
        and container.platform_sensitive is not None
        and container.platform_tokens is not None
    ):

        @app.get("/v1/platform/tenants/{tenant_id}/subjects/{subject_id}/identity")
        async def platform_read_sensitive_identity(
            request: Request,
            tenant_id: UUID,
            subject_id: UUID,
            grant_id: UUID,
            context: PlatformAccessDependency,
        ):
            identity = await container.platform_subjects.read_identity(
                tenant_id,
                subject_id,
            )
            result = await container.platform_sensitive.read_identity(
                context,
                grant_id=grant_id,
                tenant_id=tenant_id,
                subject_id=subject_id,
                identity_loader=lambda: identity,
            )
            return _data_response(request, result)

    @app.post("/v1/operations/sites")
    async def operations_create_site(
        request: Request,
        body: SiteCreateRequest,
        context: OperationsDependency,
    ):
        result = await operations_service().create_site(context, body)
        return _data_response(request, result, 201)

    @app.post("/v1/operations/devices")
    async def operations_register_device(
        request: Request,
        body: DeviceRegistrationRequest,
        context: OperationsDependency,
    ):
        result = await operations_service().register_device(context, body)
        return _data_response(request, result, 201)

    @app.post("/v1/operations/terminals/{terminal_id}/devices/{device_id}")
    async def operations_bind_device(
        request: Request,
        terminal_id: UUID,
        device_id: UUID,
        context: OperationsDependency,
    ):
        result = await operations_service().bind_device(context, terminal_id, device_id)
        return _data_response(request, result, 201)

    @app.post("/v1/operations/terminals/{terminal_id}/status")
    async def operations_set_terminal_status(
        request: Request,
        terminal_id: UUID,
        body: TerminalStatusChangeRequest,
        context: OperationsDependency,
    ):
        await operations_service().set_terminal_status(context, terminal_id, body.status)
        return _data_response(
            request,
            {"terminal_id": terminal_id, "status": body.status},
        )

    @app.post("/v1/operations/activation-codes")
    async def operations_issue_activation_code(
        request: Request,
        body: ActivationCodeIssueRequest,
        context: OperationsDependency,
    ):
        result = await operations_service().issue_activation_code(
            context,
            site_id=body.site_id,
            device_id=body.device_id,
            expires_at=body.expires_at,
        )
        return _data_response(request, result, 201)

    @app.post("/v1/operations/licenses")
    async def operations_issue_license(
        request: Request,
        body: LicenseIssueRequest,
        context: OperationsDependency,
    ):
        result = await operations_service().issue_license(context, body)
        return _data_response(request, result, 201)

    @app.post("/v1/operations/licenses/{license_id}/renew")
    async def operations_renew_license(
        request: Request,
        license_id: UUID,
        body: LicenseRenewRequest,
        context: OperationsDependency,
    ):
        result = await operations_service().renew_license(context, license_id, body)
        return _data_response(request, result, 201)

    @app.post("/v1/operations/licenses/{license_id}/revoke")
    async def operations_revoke_license(
        request: Request,
        license_id: UUID,
        body: LicenseRevokeRequest,
        context: OperationsDependency,
    ):
        result = await operations_service().revoke_license(
            context,
            license_id,
            reason_code=body.reason_code,
        )
        return _data_response(request, result, 201)

    @app.get("/v1/operations/terminals/{terminal_id}/health")
    async def operations_terminal_health(
        request: Request,
        terminal_id: UUID,
        context: OperationsDependency,
    ):
        result = await operations_service().get_terminal_health(context, terminal_id)
        return _data_response(request, result)

    @app.post("/v1/operations/upgrade-policies")
    async def operations_create_upgrade_policy(
        request: Request,
        body: UpgradePolicyRequest,
        context: OperationsDependency,
    ):
        result = await operations_service().create_upgrade_policy(context, body)
        return _data_response(request, result, 201)

    @app.post("/v1/operations/upgrade-policies/{policy_id}/status")
    async def operations_set_upgrade_policy_status(
        request: Request,
        policy_id: UUID,
        body: UpgradePolicyStatusRequest,
        context: OperationsDependency,
    ):
        result = await operations_service().set_upgrade_policy_status(
            context,
            policy_id,
            body.status,
        )
        return _data_response(request, result)

    @app.post("/v1/operations/data-access-authorizations")
    async def operations_authorize_data_access(
        request: Request,
        body: DataAccessRequest,
        context: OperationsDependency,
    ):
        result = await operations_service().authorize_data_access(context, body)
        return _data_response(request, result)

    @app.post("/v1/terminals/enroll")
    async def enroll_terminal(
        request: Request,
        body: EnrollmentRequest,
        idempotency_key: Annotated[
            str,
            Header(alias="Idempotency-Key", min_length=1, max_length=256),
        ],
    ):
        if container.devices is None:
            raise RepositoryUnavailable("终端激活服务暂不可用")
        result = await container.devices.enroll(body, idempotency_key)
        return _data_response(request, result, 201)

    @app.post("/v1/terminals/{terminal_id}/heartbeats")
    async def record_terminal_heartbeat(
        request: Request,
        terminal_id: UUID,
        body: HeartbeatRequest,
        context: HeartbeatDependency,
        idempotency_key: Annotated[
            str,
            Header(alias="Idempotency-Key", min_length=1, max_length=256),
        ],
    ):
        service = container.heartbeats or container.devices
        if service is None:
            raise RepositoryUnavailable("终端心跳服务暂不可用")
        result = await service.record_heartbeat(
            context,
            terminal_id,
            body,
            idempotency_key,
        )
        return _data_response(request, result)

    @app.post("/v1/sessions")
    async def create_session(
        request: Request,
        body: SessionCreateRequest,
        context: DataDependency,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=256)],
    ):
        result = await container.ingestion.create_session(context, body, idempotency_key)
        return _data_response(request, result, 200 if result.idempotent_replay else 201)

    @app.post("/v1/subjects/resolve")
    async def resolve_subject(
        request: Request,
        body: SubjectResolveRequest,
        context: DataDependency,
    ):
        result = await container.subjects.resolve(context, body)
        if result is None:
            raise ResourceNotFound("当前租户内未找到该受试者编号")
        return _data_response(request, result)

    @app.post("/v1/subjects")
    async def create_subject(
        request: Request,
        body: SubjectCreateRequest,
        context: DataDependency,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=256)],
    ):
        result = await container.subjects.create_subject(context, body, idempotency_key)
        return _data_response(request, result, 200 if result.conflict else 201)

    @app.post("/v1/consents")
    async def create_consent(
        request: Request,
        body: ConsentCreateRequest,
        context: DataDependency,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=256)],
    ):
        result = await container.subjects.create_consent(context, body, idempotency_key)
        return _data_response(request, result, 201)

    @app.post("/v1/consents/{consent_record_id}/revoke")
    async def revoke_consent(
        request: Request,
        consent_record_id: UUID,
        body: ConsentRevokeRequest,
        context: DataDependency,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=256)],
    ):
        result = await container.subjects.revoke_consent(
            context, consent_record_id, body, idempotency_key
        )
        return _data_response(request, result)

    @app.put("/v1/sessions/{session_id}/segments/{segment_index}")
    async def put_segment(
        request: Request,
        session_id: UUID,
        segment_index: int,
        context: DataDependency,
        content_sha256: Annotated[str, Header(alias="X-Content-SHA256")],
        schema_version: Annotated[str, Header(alias="X-Schema-Version")],
        metadata_header: Annotated[str, Header(alias="X-Segment-Metadata")],
    ):
        try:
            metadata = decode_segment_metadata(metadata_header)
        except ValueError as exc:
            raise RequestContractError("X-Segment-Metadata 无效") from exc
        if metadata.sha256 != content_sha256:
            raise RequestContractError("X-Content-SHA256 与分段元数据不一致")
        if metadata.payload_schema_version != schema_version:
            raise RequestContractError("X-Schema-Version 与分段元数据不一致")
        result = await container.ingestion.put_segment(
            context, session_id, segment_index, metadata, request.stream()
        )
        return _data_response(request, result, 200 if result.idempotent_replay else 201)

    @app.get("/v1/sessions/{session_id}/segments")
    async def list_segments(
        request: Request, session_id: UUID, context: DataDependency
    ):
        result = await container.ingestion.list_segments(context, session_id)
        return _data_response(request, result)

    @app.post("/v1/sessions/{session_id}/complete")
    async def complete_session(
        request: Request,
        session_id: UUID,
        body: SessionManifest,
        context: DataDependency,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=256)],
        content_sha256: Annotated[str, Header(alias="X-Content-SHA256")],
        schema_version: Annotated[str, Header(alias="X-Schema-Version")],
    ):
        if body.schema_version != schema_version:
            raise RequestContractError("X-Schema-Version 与最终清单不一致")
        result = await container.ingestion.complete_session(
            context, session_id, body, content_sha256, idempotency_key
        )
        return _data_response(request, result)

    @app.get("/v1/sessions/{session_id}/status")
    async def session_status(
        request: Request, session_id: UUID, context: DataDependency
    ):
        result = await container.ingestion.get_status(context, session_id)
        return _data_response(request, result)

    return app
