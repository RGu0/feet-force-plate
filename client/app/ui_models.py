from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ScreeningRecordRow:
    subject_display_id: str
    performed_at_label: str
    screening_label: str
    report_status_label: str
    performed_on: date | None = None


@dataclass(frozen=True, slots=True)
class DashboardSnapshot:
    organization_name: str
    device_status: str
    sync_status: str
    pending_summary: str
    recent_records: tuple[ScreeningRecordRow, ...]


@dataclass(frozen=True, slots=True)
class SupportSnapshot:
    device_status: str
    sync_status: str
    pending_summary: str
    app_version: str


class UiReadModelPort(Protocol):
    """Read-only presentation data owned by adapters, never by Qt widgets."""

    def dashboard_snapshot(self) -> DashboardSnapshot: ...

    def recent_records(self, *, query: str = "") -> tuple[ScreeningRecordRow, ...]: ...

    def support_snapshot(self) -> SupportSnapshot: ...
