from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class HoldApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    session_id: UUID
    ticket_reference: str
    reason_code: Literal["IDENTITY_UNVERIFIED"]


class HoldApplyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticket_reference: str
    reason_code: Literal["IDENTITY_UNVERIFIED"]


@dataclass(frozen=True, slots=True)
class SessionHoldRecord:
    hold_id: UUID
    tenant_id: UUID
    session_id: UUID
    state: Literal["HELD", "RELEASED"]
    reason_code: str
    applied_at: datetime


@dataclass(frozen=True, slots=True)
class SessionHoldStatus:
    held: bool
    hold_id: UUID | None = None
    state: str | None = None
