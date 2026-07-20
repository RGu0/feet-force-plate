from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, Header, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from cloud.api.auth import TerminalContext, TerminalTokenIssuer
from cloud.api.errors import (
    AuthenticationError,
    PlatformError,
    RequestContractError,
    ResourceNotFound,
    TenantAccessDenied,
)
from cloud.ingestion.service import IngestionService
from shared.contracts.client_sync import decode_segment_metadata
from shared.contracts.cloud import (
    ConsentCreateRequest,
    ConsentRevokeRequest,
    SessionCreateRequest,
    SessionManifest,
    SubjectCreateRequest,
    SubjectResolveRequest,
)


@dataclass(frozen=True, slots=True)
class ServiceContainer:
    ingestion: IngestionService
    token_issuer: TerminalTokenIssuer
    subjects: object


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
        terminal_id: Annotated[UUID, Header(alias="X-Terminal-ID")],
    ) -> TerminalContext:
        scheme, separator, token = authorization.partition(" ")
        if separator != " " or scheme.lower() != "bearer" or not token:
            raise AuthenticationError("缺少有效终端 Bearer 凭据")
        context = container.token_issuer.verify(token)
        if context.terminal_id != terminal_id:
            raise TenantAccessDenied(
                "X-Terminal-ID 与终端凭据不一致", terminal_id=str(terminal_id)
            )
        return context

    TerminalDependency = Annotated[TerminalContext, Depends(terminal_context)]

    @app.post("/v1/sessions")
    async def create_session(
        request: Request,
        body: SessionCreateRequest,
        context: TerminalDependency,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=256)],
    ):
        result = await container.ingestion.create_session(context, body, idempotency_key)
        return _data_response(request, result, 200 if result.idempotent_replay else 201)

    @app.post("/v1/subjects/resolve")
    async def resolve_subject(
        request: Request,
        body: SubjectResolveRequest,
        context: TerminalDependency,
    ):
        result = await container.subjects.resolve(context, body)
        if result is None:
            raise ResourceNotFound("当前租户内未找到该受试者编号")
        return _data_response(request, result)

    @app.post("/v1/subjects")
    async def create_subject(
        request: Request,
        body: SubjectCreateRequest,
        context: TerminalDependency,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=256)],
    ):
        result = await container.subjects.create_subject(context, body, idempotency_key)
        return _data_response(request, result, 200 if result.conflict else 201)

    @app.post("/v1/consents")
    async def create_consent(
        request: Request,
        body: ConsentCreateRequest,
        context: TerminalDependency,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=256)],
    ):
        result = await container.subjects.create_consent(context, body, idempotency_key)
        return _data_response(request, result, 201)

    @app.post("/v1/consents/{consent_record_id}/revoke")
    async def revoke_consent(
        request: Request,
        consent_record_id: UUID,
        body: ConsentRevokeRequest,
        context: TerminalDependency,
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
        context: TerminalDependency,
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
        request: Request, session_id: UUID, context: TerminalDependency
    ):
        result = await container.ingestion.list_segments(context, session_id)
        return _data_response(request, result)

    @app.post("/v1/sessions/{session_id}/complete")
    async def complete_session(
        request: Request,
        session_id: UUID,
        body: SessionManifest,
        context: TerminalDependency,
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
        request: Request, session_id: UUID, context: TerminalDependency
    ):
        result = await container.ingestion.get_status(context, session_id)
        return _data_response(request, result)

    return app
