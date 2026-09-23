"""Tenant-scoped read models for the authenticated institution workbench."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .institution_store import InstitutionLocalStore
from .ui_models import DashboardSnapshot, ScreeningRecordRow, SupportSnapshot


class _OfflineSnapshot(Protocol):
    pending_session_count: int


class _PhysicalStore(Protocol):
    def offline_snapshot(self) -> _OfflineSnapshot: ...


@dataclass(slots=True)
class InstitutionUiReadModels:
    institution: InstitutionLocalStore
    tenant_id: str
    physical_store: _PhysicalStore
    app_version: str
    organization_name: str = "康健社区健康服务中心"

    def recent_records(self, *, query: str = "") -> tuple[ScreeningRecordRow, ...]:
        return self.institution.recent_records(tenant_id=self.tenant_id, query=query)

    def dashboard_snapshot(self) -> DashboardSnapshot:
        records = self.recent_records()
        return DashboardSnapshot(
            organization_name=self.organization_name,
            device_status="设备已就绪",
            sync_status="网络正常",
            pending_summary=self._pending_summary(),
            recent_records=records,
        )

    def support_snapshot(self) -> SupportSnapshot:
        return SupportSnapshot(
            device_status="设备已就绪",
            sync_status="网络正常",
            pending_summary=self._pending_summary(),
            app_version=self.app_version,
        )

    def _pending_summary(self) -> str:
        snapshot = self.physical_store.offline_snapshot()
        return f"待同步数据：{snapshot.pending_session_count} 次"
