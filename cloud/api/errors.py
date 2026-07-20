from __future__ import annotations

from typing import Any


class PlatformError(Exception):
    code = "E-CLD-500"
    http_status = 500
    retryable = False
    action = "CONTACT_SUPPORT"

    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class AuthenticationError(PlatformError):
    code = "E-AUT-401"
    http_status = 401
    action = "REFRESH_CREDENTIAL"


class ActivationCodeInvalid(AuthenticationError):
    code = "E-ACT-401"
    action = "REQUEST_ACTIVATION_CODE"


class TenantAccessDenied(PlatformError):
    code = "E-AUT-403"
    http_status = 403
    action = "CONTACT_ADMINISTRATOR"


class ResourceNotFound(PlatformError):
    code = "E-API-404"
    http_status = 404
    action = "VERIFY_REFERENCE"


class RequestContractError(PlatformError):
    code = "E-API-400"
    http_status = 400
    action = "FIX_REQUEST"


class IdempotencyConflict(PlatformError):
    code = "E-API-409"
    http_status = 409
    action = "EXPORT_DIAGNOSTIC"


class SegmentDigestConflict(PlatformError):
    code = "E-SYN-409"
    http_status = 409
    action = "EXPORT_DIAGNOSTIC"


class ManifestConflict(SegmentDigestConflict):
    pass


class DigestMismatch(PlatformError):
    code = "E-CLD-422"
    http_status = 422
    action = "RESEAL_SEGMENT"


class SizeMismatch(DigestMismatch):
    pass


class SchemaUnsupported(PlatformError):
    code = "E-CLD-422"
    http_status = 422
    action = "UPDATE_CLIENT"


class ManifestIncomplete(PlatformError):
    code = "E-CLD-422"
    http_status = 422
    action = "UPLOAD_MISSING_SEGMENTS"


class QualityGateRejected(PlatformError):
    code = "E-CLD-422"
    http_status = 422
    action = "REPEAT_SCREENING"


class RepositoryUnavailable(PlatformError):
    code = "E-CLD-503"
    http_status = 503
    retryable = True
    action = "RETRY_LATER"
