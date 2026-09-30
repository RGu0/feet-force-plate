from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import QCoreApplication

from client.device.acquisition import AcquisitionOutcome
from client.device.session_ui import HardwareUiFailureCode
from client.hardware_integration.live_hardware_acquisition import (
    QtLiveHardwareAcquisition,
)
from client.hardware_integration.live_physical_workflow import (
    LivePhysicalCapture,
    LiveSessionMetadata,
)
from client.hardware_standardization.dynamic_defect_mask import (
    DynamicDefectEntry,
    DynamicDefectMask,
    DynamicDefectStatus,
)


def test_unavailable_frozen_mask_rejects_before_device_or_raw_capture(tmp_path: Path) -> None:
    app = QCoreApplication.instance() or QCoreApplication([])
    connections: list[str] = []

    class Hardware:
        capture_profile_version = "test-profile/1"

        def connect_capture(self):
            connections.append("connected")
            raise AssertionError("unavailable device health must block connection")

        connect_startup = connect_capture

    class Sessions:
        def metadata(self, _session_id: str) -> LiveSessionMetadata:
            return LiveSessionMetadata(
                "subject",
                "consent",
                datetime.now(UTC),
            )

    unusable_mask = DynamicDefectMask(
        device_id="device-1",
        mask_version=7,
        policy_version="dynamic-defect-mask/generic-grid/2",
        shape=(48, 64),
        entries=tuple(
            DynamicDefectEntry(
                source_index=index,
                status=DynamicDefectStatus.REPAIRABLE,
                confirmed_observations=2,
                last_observed_session_id="prior-session",
            )
            for index in (100, 300, 500)
        ),
    )
    capture = LivePhysicalCapture(
        hardware=Hardware(),
        sessions=Sessions(),
        baseline=SimpleNamespace(reference=object()),
        physical_store=object(),
        key_provider=object(),
        spool_root=tmp_path / "spool",
        latest_frames=object(),
        formal_upload=None,
        dynamic_defect_mask_loader=lambda: unusable_mask,
    )
    completed: list[object] = []
    failures: list[str] = []
    acquisition = QtLiveHardwareAcquisition(
        capture.capture,
        prepare_session=capture.prepare_session,
        expected_stage_ids=("first",),
    )
    acquisition.set_callbacks(
        on_progress=lambda _elapsed: None,
        on_complete=completed.append,
        on_failure=failures.append,
    )

    acquisition.start_stage("blocked-session", SimpleNamespace(stage_id="first", duration_seconds=1))
    acquisition.wait_for_worker(timeout_seconds=1)
    app.processEvents()

    assert connections == []
    assert len(completed) == 1
    assert failures == []
    result = completed[0]
    assert result.acquisition.outcome is AcquisitionOutcome.INVALID
    assert result.acquisition.frames_stored == 0
    assert result.reason == "DEVICE_DYNAMIC_DEFECT_MASK_UNUSABLE"
    assert result.ui_failure.code is HardwareUiFailureCode.SENSOR_DATA_UNUSABLE
    assert not result.committed
    assert not (tmp_path / "spool").exists()
