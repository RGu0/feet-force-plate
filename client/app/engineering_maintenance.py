"""Privileged, read-only projection of the dynamic hardware defect mask.

This is an engineering boundary, not an operator or algorithm feature. It
requires an externally supplied confirmation verifier and an engineer-selected
asset ID. The projection deliberately contains only mask markers and health
status: never pressure frames, evidence counts, session identifiers, protocol
details, or repair controls.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from client.hardware_standardization.dynamic_defect_mask import (
    DeviceHealthStatus,
    DynamicDefectMaskStore,
    DynamicDefectStatus,
)


class EngineeringMaintenanceAccessDenied(PermissionError):
    """The requested engineering confirmation was not authorized."""


class EngineeringMaintenanceDeviceUnbound(LookupError):
    """No engineering-selected device ID is available for maintenance."""


class EngineeringMaintenanceConnectionUnavailable(LookupError):
    """The deployment has not configured an engineering device-ID registry."""


class EngineeringDeviceBindingStore:
    """Small, local, atomic registry for engineering-selected asset IDs.

    This registry contains no raw frames, participant data, mask content,
    credentials, port paths, USB descriptors, or hardware fingerprints.
    """

    _SCHEMA = "engineering-device-registry/1"
    _LEGACY_SCHEMA = "engineering-device-binding/1"

    def __init__(self, data_root: str | Path) -> None:
        self._path = Path(data_root) / "hardware" / "engineering-device-bindings.json"

    @property
    def selected_device_id(self) -> str | None:
        selected = self._read().get("selected_device_id")
        return selected if isinstance(selected, str) else None

    def device_ids(self) -> tuple[str, ...]:
        device_ids = self._read().get("device_ids")
        assert isinstance(device_ids, list)
        return tuple(device_ids)

    def register_device_id(self, device_id: str) -> None:
        device_id = device_id.strip()
        if not device_id:
            raise ValueError("device_id is required")
        device_ids = self.device_ids()
        self._atomic_write(
            {
                "schema_version": self._SCHEMA,
                "selected_device_id": device_id,
                "device_ids": sorted({*device_ids, device_id}),
            }
        )

    def _read(self) -> dict[str, object]:
        if not self._path.exists():
            return {"schema_version": self._SCHEMA, "selected_device_id": None, "device_ids": []}
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("engineering device binding registry is unreadable") from exc
        if not isinstance(payload, dict):
            raise ValueError("engineering device binding registry is invalid")
        if payload.get("schema_version") == self._LEGACY_SCHEMA:
            bindings = payload.get("bindings")
            selected = payload.get("selected_device_id")
            if not isinstance(bindings, dict):
                raise ValueError("engineering device binding registry is invalid")
            device_ids = sorted(device_id for device_id in bindings if isinstance(device_id, str))
            return {
                "schema_version": self._SCHEMA,
                "selected_device_id": selected if selected in device_ids else None,
                "device_ids": device_ids,
            }
        device_ids = payload.get("device_ids")
        selected = payload.get("selected_device_id")
        if (
            payload.get("schema_version") != self._SCHEMA
            or not isinstance(device_ids, list)
            or not all(isinstance(device_id, str) and device_id for device_id in device_ids)
            or selected is not None and (not isinstance(selected, str) or selected not in device_ids)
        ):
            raise ValueError("engineering device binding registry is invalid")
        return {
            "schema_version": self._SCHEMA,
            "selected_device_id": selected,
            "device_ids": sorted(set(device_ids)),
        }

    def _atomic_write(self, payload: dict[str, object]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
        with NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=self._path.parent, delete=False
        ) as temporary:
            temporary.write(encoded)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        try:
            os.replace(temporary_path, self._path)
        finally:
            temporary_path.unlink(missing_ok=True)


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
    """Gate and project one engineer-selected device's saved mask.

    ``confirmation_verifier`` belongs to the deployment/authentication layer;
    this module neither stores nor compares a shared secret.  It is therefore
    safe for the ordinary desktop composition to omit this service entirely.
    """

    def __init__(
        self,
        *,
        bound_device_id: str | None = None,
        mask_store_for_device: Callable[[str], DynamicDefectMaskStore | None],
        confirmation_verifier: Callable[[str], bool] | None = None,
        binding_store: EngineeringDeviceBindingStore | None = None,
        connected_device_identity: Callable[[], str | None] | None = None,
        authorization_verifier: Callable[[], bool] | None = None,
    ) -> None:
        self._bound_device_id = bound_device_id.strip() if bound_device_id else None
        self._mask_store_for_device = mask_store_for_device
        self._confirmation_verifier = confirmation_verifier
        self._binding_store = binding_store
        self._authorization_verifier = authorization_verifier

    def device_ids(self) -> tuple[str, ...]:
        """Return only registered asset IDs, never physical connection details."""

        if self._binding_store is None:
            return (self._bound_device_id,) if self._bound_device_id else ()
        return self._binding_store.device_ids()

    def selected_device_id(self) -> str | None:
        if self._binding_store is None:
            return self._bound_device_id
        return self._binding_store.selected_device_id

    def bind_current_device(
        self, confirmation_or_device_id: str, device_id: str | None = None
    ) -> None:
        """Explicitly register and select an engineer-entered asset ID.

        This is intentionally an engineering-only confirmation path. It does
        not derive an ID from a USB device and does not touch a mask.
        """

        if device_id is None:
            self._require_authorization()
            device_id = confirmation_or_device_id
        else:
            self._require_authorization(confirmation_or_device_id)
        if self._binding_store is None:
            raise EngineeringMaintenanceConnectionUnavailable(
                "device registry is not configured by this deployment"
            )
        self._binding_store.register_device_id(device_id)

    def read_distribution(
        self, confirmation: str | None = None
    ) -> EngineeringMaintenanceSnapshot:
        """Return the saved mask only after authorization; never mutate it."""

        self._require_authorization(confirmation)
        bound_device_id = self._selected_bound_device_id()
        if not bound_device_id:
            raise EngineeringMaintenanceDeviceUnbound(
                "no engineering device ID is selected for this terminal"
            )
        store = self._mask_store_for_device(bound_device_id)
        if store is None or store.device_id != bound_device_id:
            raise EngineeringMaintenanceDeviceUnbound(
                "the selected device has no matching maintenance mask store"
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

    def _selected_bound_device_id(self) -> str | None:
        if self._binding_store is None:
            return self._bound_device_id
        return self._binding_store.selected_device_id

    def _require_authorization(self, confirmation: str | None = None) -> None:
        if self._authorization_verifier is not None:
            if not self._authorization_verifier():
                raise EngineeringMaintenanceAccessDenied("engineering authorization denied")
            return
        if self._confirmation_verifier is None or confirmation is None:
            raise EngineeringMaintenanceAccessDenied("engineering authorization denied")
        if not self._confirmation_verifier(confirmation):
            raise EngineeringMaintenanceAccessDenied("engineering confirmation denied")
