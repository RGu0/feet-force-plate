"""Terminal-safe contracts for controlled offline identity recovery."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints, model_validator

from .cloud import ContractModel, Sha256Hex


class RecoveryCaseCreateRequest(ContractModel):
    session_id: UUID
    original_subject_uuid: UUID
    cloud_subject_uuid: UUID
    envelope_sha256: Sha256Hex
    identifier_issuer: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    identifier_type: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    terminal_id: UUID

    @model_validator(mode="after")
    def different_subjects(self):
        if self.original_subject_uuid == self.cloud_subject_uuid:
            raise ValueError("recovery requires distinct local and cloud subjects")
        return self


class RecoveryCaseSummary(ContractModel):
    case_id: UUID
    session_id: UUID
    status: Literal["PENDING", "MATCHED", "DENIED", "EXPIRED"]
    masked_clue: str | None = None
    created_at: datetime
    receipt_id: UUID | None = None
    receipt_expires_at: datetime | None = None


class RecoveryCaseCreateResponse(ContractModel):
    case: RecoveryCaseSummary
    idempotent_replay: bool = Field(default=False)


class RecoveryComparisonRequest(ContractModel):
    tenant_id: UUID
    grant_id: UUID
    original_name: Annotated[str, StringConstraints(max_length=256)]
    original_contact: Annotated[str, StringConstraints(max_length=512)]
    ticket_reference: Annotated[str, StringConstraints(min_length=1, max_length=128)]


class RecoveryComparisonResult(ContractModel):
    case_id: UUID
    decision: Literal["MATCHED", "NOT_VERIFIED"]
    receipt_id: UUID | None = None
    receipt_expires_at: datetime | None = None
