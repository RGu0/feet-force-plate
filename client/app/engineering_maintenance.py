"""Privileged, read-only projection of the dynamic hardware defect mask.

This is an engineering boundary, not an operator or algorithm feature.  It
requires an externally supplied confirmation verifier and an already-bound
stable physical device ID.  The projection deliberately contains only mask
markers and health status: never pressure frames, evidence counts, session
identifiers, protocol details, or repair controls.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from client.hardware_standardization.dynamic_defect_mask import (
    DeviceHealthStatus,
    DynamicDefectMaskStore,
    DynamicDefectStatus,
)


class EngineeringMaintenanceAccessDenied(PermissionError):
    """The requested engineering confirmation was not authorized."""


class EngineeringMaintenanceDeviceUnbound(LookupError):
    """No stable physical-device binding is available for maintenance."""


@dataclass(frozen=True, slots=True)
class EngineeringDefectCell:
    """One marked board cell, with no raw value or session evidence."""

    row: int
    column: int
    status: DynamicDefectStatus


@dataclass(frozen=True, slots=True)
class EngineeringMaintenanceSnapshot:
    """Read-only board-health distribution for a confirmed engineer."""

    device_id: str
    shape: tuple[int, int]
    mask_version: int
    health_status: DeviceHealthStatus
    status_counts: dict[DynamicDefectStatus, int]
    marked_cells: tuple[EngineeringDefectCell, ...]


class EngineeringMaintenanceService:
    """Gate and project one already-bound physical device's saved mask.

    ``confirmation_verifier`` belongs to the deployment/authentication layer;
    this module neither stores nor compares a shared secret.  It is therefore
    safe for the ordinary desktop composition to omit this service entirely.
    """

    def __init__(
        self,
        *,
        bound_device_id: str | None,
        mask_store_for_device: Callable[[str], DynamicDefectMaskStore | None],
        confirmation_verifier: Callable[[str], bool],
    ) -> None:
        self._bound_device_id = bound_device_id.strip() if bound_device_id else None
        self._mask_store_for_device = mask_store_for_device
        self._confirmation_verifier = confirmation_verifier

    def read_distribution(self, confirmation: str) -> EngineeringMaintenanceSnapshot:
        """Return the saved mask only after authorization; never mutate it."""

        if not self._confirmation_verifier(confirmation):
            raise EngineeringMaintenanceAccessDenied("engineering confirmation denied")
        if not self._bound_device_id:
            raise EngineeringMaintenanceDeviceUnbound(
                "no stable physical device is bound to this terminal"
            )
        store = self._mask_store_for_device(self._bound_device_id)
        if store is None or store.device_id != self._bound_device_id:
            raise EngineeringMaintenanceDeviceUnbound(
                "the selected device has no verified maintenance binding"
            )
        mask = store.load_for_session()
        counts = {
            status: sum(entry.status is status for entry in mask.entries)
            for status in DynamicDefectStatus
        }
        rows, _columns = mask.shape
        marked_cells = tuple(
            EngineeringDefectCell(
                row=entry.source_index % rows,
                column=entry.source_index // rows,
                status=entry.status,
            )
            for entry in mask.entries
        )
        return EngineeringMaintenanceSnapshot(
            device_id=mask.device_id,
            shape=mask.shape,
            mask_version=mask.mask_version,
            health_status=mask.health_status(store.policy),
            status_counts=counts,
            marked_cells=marked_cells,
        )
