from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QLabel, QLineEdit, QPushButton

from client.app.engineering_maintenance import (
    EngineeringMaintenanceAccessDenied,
    EngineeringMaintenanceDeviceUnbound,
    EngineeringMaintenanceService,
)
from client.app.controller import ApplicationController
from client.app.pages import PageId
from client.app.qt_shell import ScreeningWindow
from client.hardware_standardization.dynamic_defect_mask import (
    DynamicDefectEntry,
    DynamicDefectMask,
    DynamicDefectMaskStore,
    DynamicDefectPolicy,
    DynamicDefectStatus,
)
from client.workflow.models import WorkflowState
from client.workflow.state_machine import ScreeningStep


class _HomeCoordinator:
    @property
    def state(self) -> WorkflowState:
        return WorkflowState(step=ScreeningStep.HOME)


def _store(root: Path) -> DynamicDefectMaskStore:
    return DynamicDefectMaskStore(
        data_root=root,
        device_id="physical-device-7",
        shape=(4, 5),
        policy=DynamicDefectPolicy(),
    )


def _write_mask(store: DynamicDefectMaskStore) -> None:
    store._atomic_write(
        DynamicDefectMask(
            device_id=store.device_id,
            mask_version=3,
            policy_version=store.policy.version,
            shape=store.shape,
            entries=(
                DynamicDefectEntry(
                    source_index=6,
                    status=DynamicDefectStatus.SUSPECT,
                    confirmed_observations=1,
                    last_observed_session_id="masked-from-maintenance",
                ),
                DynamicDefectEntry(
                    source_index=14,
                    status=DynamicDefectStatus.REPAIRABLE,
                    confirmed_observations=2,
                    last_observed_session_id="masked-from-maintenance",
                ),
            ),
        )
    )


def test_engineering_maintenance_requires_authorized_confirmation_before_reading(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    _write_mask(store)
    service = EngineeringMaintenanceService(
        bound_device_id=store.device_id,
        mask_store_for_device=lambda device_id: store if device_id == store.device_id else None,
        confirmation_verifier=lambda confirmation: confirmation == "approved",
    )

    with pytest.raises(EngineeringMaintenanceAccessDenied):
        service.read_distribution("not-approved")

    snapshot = service.read_distribution("approved")

    assert snapshot.mask_version == 3
    assert snapshot.device_id == "physical-device-7"
    assert {(cell.row, cell.column, cell.status) for cell in snapshot.marked_cells} == {
        (2, 1, DynamicDefectStatus.SUSPECT),
        (2, 3, DynamicDefectStatus.REPAIRABLE),
    }
    assert snapshot.status_counts == {
        DynamicDefectStatus.SUSPECT: 1,
        DynamicDefectStatus.REPAIRABLE: 1,
    }


def test_engineering_maintenance_rejects_an_unbound_device_and_never_guesses_identity(
    tmp_path: Path,
) -> None:
    service = EngineeringMaintenanceService(
        bound_device_id=None,
        mask_store_for_device=lambda _device_id: _store(tmp_path),
        confirmation_verifier=lambda _confirmation: True,
    )

    with pytest.raises(EngineeringMaintenanceDeviceUnbound):
        service.read_distribution("approved")


def test_engineering_distribution_is_read_only_and_excludes_frame_evidence(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _write_mask(store)
    before = store.path.read_bytes()
    snapshot = EngineeringMaintenanceService(
        bound_device_id=store.device_id,
        mask_store_for_device=lambda _device_id: store,
        confirmation_verifier=lambda _confirmation: True,
    ).read_distribution("approved")

    assert store.path.read_bytes() == before
    public_fields = set(snapshot.__dataclass_fields__)
    assert public_fields == {
        "device_id",
        "shape",
        "mask_version",
        "health_status",
        "status_counts",
        "marked_cells",
    }
    assert "raw" not in repr(snapshot).lower()
    assert "session" not in repr(snapshot).lower()


def test_support_page_exposes_engineering_distribution_only_when_configured(
    qtbot,
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    _write_mask(store)
    service = EngineeringMaintenanceService(
        bound_device_id=store.device_id,
        mask_store_for_device=lambda _device_id: store,
        confirmation_verifier=lambda confirmation: confirmation == "approved",
    )
    window = ScreeningWindow()
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    window.show_page(PageId.SUPPORT)
    entry = window.findChild(QPushButton, "OPEN_ENGINEERING_MAINTENANCE")

    assert not entry.isVisible()
    window.set_engineering_maintenance_available(True)
    assert entry.isVisible()

    window.show_engineering_maintenance(service)
    dialog = window.findChild(QDialog, "engineeringMaintenanceDialog")
    assert dialog is not None
    confirmation = dialog.findChild(QLineEdit, "engineeringMaintenanceConfirmation")
    qtbot.keyClicks(confirmation, "approved")
    qtbot.mouseClick(
        dialog.findChild(QPushButton, "CONFIRM_ENGINEERING_MAINTENANCE"),
        Qt.MouseButton.LeftButton,
    )

    assert "SUSPECT 1" in dialog.findChild(QLabel, "engineeringMaintenanceSummary").text()
    assert "REPAIRABLE 1" in dialog.findChild(QLabel, "engineeringMaintenanceSummary").text()
    assert "原始压力" in dialog.findChild(QLabel, "engineeringMaintenanceBoundary").text()


def test_controller_wires_the_engineering_maintenance_entry(qtbot, tmp_path: Path) -> None:
    store = _store(tmp_path)
    service = EngineeringMaintenanceService(
        bound_device_id=store.device_id,
        mask_store_for_device=lambda _device_id: store,
        confirmation_verifier=lambda _confirmation: True,
    )
    controller = ApplicationController(
        _HomeCoordinator(), engineering_maintenance=service
    )
    qtbot.addWidget(controller.window)
    controller.window.show()
    qtbot.waitExposed(controller.window)
    controller.window.show_page(PageId.SUPPORT)

    qtbot.mouseClick(
        controller.window.findChild(QPushButton, "OPEN_ENGINEERING_MAINTENANCE"),
        Qt.MouseButton.LeftButton,
    )

    assert controller.window.findChild(QDialog, "engineeringMaintenanceDialog") is not None
