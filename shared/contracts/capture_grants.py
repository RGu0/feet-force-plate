"""Transport contracts for one-time capture grants and migration permits.

These values carry credentials; validation here does not prove authorization.
"""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, SecretStr, StringConstraints, field_validator

from .access_control import HardwareIdentity
from .cloud import ContractModel, Sha256Hex


NonemptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class _TokenContract(ContractModel):
    token: SecretStr

    @field_validator("token")
    @classmethod
    def require_opaque_token(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < 20:
            raise ValueError("authorization token must contain at least 20 characters")
        return value


class CaptureGrant(_TokenContract):
    session_id: UUID


class CaptureGrantBatchRequest(ContractModel):
    count: Annotated[int, Field(ge=1, le=50)]


class CaptureGrantBatchResponse(ContractModel):
    grants: tuple[CaptureGrant, ...]


class RetireCaptureGrantRequest(ContractModel):
    session_id: UUID
    reason: NonemptyText


class CaptureCredential(_TokenContract):
    session_id: UUID
    kind: Literal["grant", "migration_permit"]


class SessionAuthorization(CaptureCredential):
    manifest_sha256: Sha256Hex

    def headers(self) -> dict[str, str]:
        return {
            "X-Capture-Authorization": f"{self.kind} {self.token.get_secret_value()}",
            "X-Expected-Manifest-SHA256": self.manifest_sha256,
        }


class UploadMigrationPermitRequest(ContractModel):
    tenant_id: UUID
    account_id: UUID
    license_id: UUID
    installation_id: UUID
    hardware_id: HardwareIdentity
    session_id: UUID
    request_sha256: Sha256Hex
    manifest_sha256: Sha256Hex
    evidence_reference: NonemptyText
    reason: NonemptyText
    identity_conflict: bool
    reconciliation_reference: NonemptyText | None
    local_valid_reviewed: bool
    immutable_manifest_reviewed: bool
    original_consent_reviewed: bool
    historical_authorization_reviewed: bool


class MigrationPermitResponse(_TokenContract):
    session_id: UUID
