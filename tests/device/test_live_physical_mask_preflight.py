from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from client.app.controller import ApplicationController
from client.app.pages import PageId
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
from client.workflow.coordinator import ScreeningCoordinator
from client.workflow.models import (
    ClientAction,
    PreflightCheck,
    PreflightSummary,
    SessionValidity,
)
from client.workflow.protocol import default_standard_protocol
from client.workflow.state_machine import ScreeningStep


class _Preflight:
    def __init__(self) -> None:
        self.runs = 0

    def run_preflight(self) -> PreflightSummary:
        self.runs += 1
        return PreflightSummary(checks=(PreflightCheck("device", True),))


class _Sessions:
    def __init__(self) -> None:
        self.created: list[str] = []
        self.incomplete: list[str] = []

    def create_session(self, _context, _protocol) -> str:
        session_id = f"screening-{len(self.created) + 1}"
        self.created.append(session_id)
        return session_id

    def metadata(self, _session_id: str) -> LiveSessionMetadata:
        return LiveSessionMetadata("subject", "consent", datetime.now(UTC))

    def mark_incomplete(self, session_id: str) -> None:
        self.incomplete.append(session_id)


class _Telemetry:
    def __init__(self) -> None:
        self.errors: list[tuple[str, str | None, str]] = []

    def record_error(self, *, code, session_id, technical_detail) -> None:
        self.errors.append((code, session_id, technical_detail))


def _start_stage(coordinator: ScreeningCoordinator) -> None:
    assert coordinator.enter_position_guidance()
    coordinator.observe_position(
        now_seconds=0, contact_ready=True, in_valid_area=True
    )
    coordinator.observe_position(
        now_seconds=4, contact_ready=True, in_valid_area=True
    )
    assert coordinator.start_acquisition()


def test_unavailable_frozen_mask_closes_session_and_leaves_ui_retryable(
    qtbot, tmp_path: Path
) -> None:
    connections: list[str] = []

    class Hardware:
        capture_profile_version = "test-profile/1"

        def connect_capture(self):
            connections.append("connected")
            raise AssertionError("unavailable device health must block connection")

        connect_startup = connect_capture

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
    sessions = _Sessions()
    preflight = _Preflight()
    telemetry = _Telemetry()
    capture = LivePhysicalCapture(
        hardware=Hardware(),
        sessions=sessions,
        baseline=SimpleNamespace(reference=object()),
        physical_store=object(),
        key_provider=object(),
        spool_root=tmp_path / "spool",
        latest_frames=object(),
        formal_upload=None,
        dynamic_defect_mask_loader=lambda: unusable_mask,
    )
    protocol = default_standard_protocol()
    acquisition = QtLiveHardwareAcquisition(
        capture.capture,
        prepare_session=capture.prepare_session,
        expected_stage_ids=tuple(stage.stage_id for stage in protocol.stages),
    )
    coordinator = ScreeningCoordinator(
        preflight=preflight,
        sessions=sessions,
        acquisition=acquisition,
        analysis=object(),
        reports=object(),
        telemetry=telemetry,
        protocol=protocol,
    )
    controller = ApplicationController(coordinator)
    qtbot.addWidget(controller.window)
    acquisition.set_callbacks(
        on_progress=controller.on_acquisition_elapsed,
        on_complete=lambda result: controller.on_live_hardware_capture_completed(
            result, record_attestations=lambda *_args, **_kwargs: None
        ),
        on_failure=controller.on_live_hardware_capture_failed,
    )

    coordinator.start_new_screening()
    coordinator.bind_participant(subject_uuid="subject", consent_record_id="consent")
    coordinator.confirm_subject()
    coordinator.complete_profile()
    coordinator.confirm_consent()
    assert coordinator.run_preflight()
    _start_stage(coordinator)

    assert coordinator.state.step is ScreeningStep.INCOMPLETE
    assert coordinator.state.validity is SessionValidity.INCOMPLETE
    assert coordinator.state.lifecycle_status.value == "CLOSED"
    assert coordinator.state.error.code == "E-DEV-109"
    assert coordinator.state.error.action is ClientAction.RETRY_SCREENING
    assert sessions.created == ["screening-1"]
    assert sessions.incomplete == ["screening-1"]
    assert telemetry.errors == [
        ("E-DEV-109", "screening-1", "hardware_ui_failure:E-DEV-109")
    ]
    assert controller.window.current_page_id is PageId.RESULT
    assert connections == []
    assert acquisition.wait_for_worker(timeout_seconds=0.1)
    assert not (tmp_path / "spool").exists()

    controller.dispatch("RETRY_SCREENING")
    qtbot.waitUntil(lambda: coordinator.state.preflight_ready)
    assert coordinator.state.step is ScreeningStep.PREFLIGHT
    assert coordinator.state.session_id is None
    _start_stage(coordinator)

    assert coordinator.state.step is ScreeningStep.INCOMPLETE
    assert sessions.created == ["screening-1", "screening-2"]
    assert sessions.incomplete == ["screening-1", "screening-2"]
    assert controller.window.current_page_id is PageId.RESULT
    assert connections == []
    assert acquisition.wait_for_worker(timeout_seconds=0.1)
    assert not (tmp_path / "spool").exists()

    assert coordinator.state.error.code == "E-DEV-109"
