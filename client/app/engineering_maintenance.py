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
    """No stable physical-device binding is available for maintenance."""


class EngineeringMaintenanceConnectionUnavailable(LookupError):
    """The deployment cannot currently prove a stable connected-device identity."""


@dataclass(frozen=True, slots=True)
class EngineeringDeviceBinding:
    """A selected asset ID bound to an opaque, stable hardware identity.

    ``connection_id`` is supplied by the hardware/deployment layer (for example,
    a USB serial-number fingerprint).  It is deliberately not a serial path and
    is never projected to the ordinary operator UI.
    """

    device_id: str
    connection_id: str


class EngineeringDeviceBindingStore:
    """Small, local, atomic registry for engineering-selected device bindings.

    This registry contains no raw frames, participant data, mask content or
    credentials.  A connection without a hardware-provided stable identifier
    cannot be bound: a changing serial path is not a physical device identity.
    """

    _SCHEMA = "engineering-device-binding/1"

    def __init__(self, data_root: str | Path) -> None:
        self._path = Path(data_root) / "hardware" / "engineering-device-bindings.json"

    @property
    def selected_device_id(self) -> str | None:
        return self._read().get("selected_device_id")

    def device_ids(self) -> tuple[str, ...]:
        bindings = self._read().get("bindings", {})
        return tuple(sorted(bindings))

    def bind_current_connection(self, *, device_id: str, connection_id: str) -> None:
        device_id = device_id.strip()
        connection_id = connection_id.strip()
        if not device_id:
            raise ValueError("device_id is required")
        if not connection_id:
            raise EngineeringMaintenanceConnectionUnavailable(
                "no stable hardware identity is available for binding"
            )
        payload = self._read()
        bindings = dict(payload["bindings"])
        bindings[device_id] = {"connection_id": connection_id}
        self._atomic_write(
            {
                "schema_version": self._SCHEMA,
                "selected_device_id": device_id,
                "bindings": bindings,
            }
        )

    def binding_for_selected_device(self) -> EngineeringDeviceBinding | None:
        payload = self._read()
        device_id = payload.get("selected_device_id")
        binding = payload.get("bindings", {}).get(device_id)
        if not isinstance(device_id, str) or not isinstance(binding, dict):
            return None
        connection_id = binding.get("connection_id")
        if not isinstance(connection_id, str) or not connection_id:
            return None
        return EngineeringDeviceBinding(device_id=device_id, connection_id=connection_id)

    def _read(self) -> dict[str, object]:
        if not self._path.exists():
            return {"schema_version": self._SCHEMA, "selected_device_id": None, "bindings": {}}
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("engineering device binding registry is unreadable") from exc
        if (
            not isinstance(payload, dict)
            or payload.get("schema_version") != self._SCHEMA
            or not isinstance(payload.get("bindings"), dict)
        ):
            raise ValueError("engineering device binding registry is invalid")
        return payload

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
    """Gate and project one already-bound physical device's saved mask.

    ``confirmation_verifier`` belongs to the deployment/authentication layer;
    this module neither stores nor compares a shared secret.  It is therefore
    safe for the ordinary desktop composition to omit this service entirely.
    """

    def __init__(
        self,
        *,
        bound_device_id: str | None = None,
        mask_store_for_device: Callable[[str], DynamicDefectMaskStore | None],
        confirmation_verifier: Callable[[str], bool],
        binding_store: EngineeringDeviceBindingStore | None = None,
        connected_device_identity: Callable[[], str | None] | None = None,
    ) -> None:
        self._bound_device_id = bound_device_id.strip() if bound_device_id else None
        self._mask_store_for_device = mask_store_for_device
        self._confirmation_verifier = confirmation_verifier
        self._binding_store = binding_store
        self._connected_device_identity = connected_device_identity

    def device_ids(self) -> tuple[str, ...]:
        """Return only registered asset IDs, never physical connection details."""

        if self._binding_store is None:
            return (self._bound_device_id,) if self._bound_device_id else ()
        return self._binding_store.device_ids()

    def selected_device_id(self) -> str | None:
        if self._binding_store is None:
            return self._bound_device_id
        return self._binding_store.selected_device_id

    def bind_current_device(self, confirmation: str, device_id: str) -> None:
        """Explicitly bind an engineer-entered asset ID to the current hardware.

        This is intentionally an engineering-only confirmation path.  It cannot
        synthesize an identity from a port name, and it does not touch a mask.
        """

        if not self._confirmation_verifier(confirmation):
            raise EngineeringMaintenanceAccessDenied("engineering confirmation denied")
        if self._binding_store is None or self._connected_device_identity is None:
            raise EngineeringMaintenanceConnectionUnavailable(
                "device binding is not configured by this deployment"
            )
        connection_id = self._connected_device_identity()
        self._binding_store.bind_current_connection(
            device_id=device_id, connection_id=connection_id or ""
        )

    def read_distribution(self, confirmation: str) -> EngineeringMaintenanceSnapshot:
        """Return the saved mask only after authorization; never mutate it."""

        if not self._confirmation_verifier(confirmation):
            raise EngineeringMaintenanceAccessDenied("engineering confirmation denied")
        bound_device_id = self._selected_bound_device_id()
        if not bound_device_id:
            raise EngineeringMaintenanceDeviceUnbound(
                "no stable physical device is bound to this terminal"
            )
        store = self._mask_store_for_device(bound_device_id)
        if store is None or store.device_id != bound_device_id:
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

    def _selected_bound_device_id(self) -> str | None:
        if self._binding_store is None:
            return self._bound_device_id
        binding = self._binding_store.binding_for_selected_device()
        if binding is None or self._connected_device_identity is None:
            return None
        current_identity = self._connected_device_identity()
        if not current_identity or current_identity != binding.connection_id:
            return None
        return binding.device_id
