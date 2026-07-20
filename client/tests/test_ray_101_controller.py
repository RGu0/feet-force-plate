from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton

from client.app.controller import ApplicationController
from client.app.pages import PageId
from client.workflow.models import WorkflowState
from client.workflow.state_machine import ScreeningStep


class _Coordinator:
    def __init__(self) -> None:
        self._state = WorkflowState(step=ScreeningStep.HOME)
        self.exports: list[Path] = []
        self.print_count = 0

    @property
    def state(self) -> WorkflowState:
        return self._state

    def start_new_screening(self) -> None:
        self._state = WorkflowState(step=ScreeningStep.SUBJECT_IDENTIFICATION)

    def confirm_subject(self) -> None:
        self._state = WorkflowState(step=ScreeningStep.PROFILE_DETAILS)

    def complete_profile(self) -> None:
        self._state = WorkflowState(step=ScreeningStep.CONSENT_CONFIRMATION)

    def confirm_consent(self) -> None:
        self._state = WorkflowState(step=ScreeningStep.PREFLIGHT)

    def run_preflight(self) -> bool:
        self._state = WorkflowState(step=ScreeningStep.POSITION_GUIDANCE)
        return True

    def start_acquisition(self) -> bool:
        self._state = WorkflowState(step=ScreeningStep.ACQUIRING)
        return True

    def stop_acquisition(self) -> bool:
        self._state = WorkflowState(step=ScreeningStep.INCOMPLETE)
        return True

    def retry_screening(self) -> None:
        self._state = WorkflowState(step=ScreeningStep.POSITION_GUIDANCE)

    def export_current_report(self, destination: Path) -> None:
        self.exports.append(destination)

    def print_current_report(self) -> None:
        self.print_count += 1

    def complete_acquisition(self) -> None:
        self._state = WorkflowState(step=ScreeningStep.BASIC_REPORT)

    def handle_device_disconnect(self, *, technical_detail: str) -> None:
        _ = technical_detail
        self._state = WorkflowState(step=ScreeningStep.INCOMPLETE)

    def start_next_screening(self) -> None:
        self._state = WorkflowState(step=ScreeningStep.SUBJECT_IDENTIFICATION)


def test_primary_button_dispatches_to_coordinator_and_refreshes_page(qtbot) -> None:
    controller = ApplicationController(_Coordinator())
    qtbot.addWidget(controller.window)
    button = controller.window.page_widget(PageId.WORKBENCH).findChild(
        QPushButton,
        "START_NEW_SCREENING",
    )

    qtbot.mouseClick(button, Qt.MouseButton.LeftButton)

    assert controller.window.current_page_id == PageId.SUBJECT_IDENTIFICATION


def test_controller_drives_the_operator_path_and_deferred_preflight(qtbot) -> None:
    controller = ApplicationController(_Coordinator())
    qtbot.addWidget(controller.window)

    controller.dispatch("START_NEW_SCREENING")
    controller.dispatch("CONFIRM_SUBJECT")
    controller.dispatch("SKIP_PROFILE")
    controller.dispatch("CONFIRM_CONSENT")

    assert controller.window.current_page_id == PageId.PREFLIGHT
    qtbot.waitUntil(
        lambda: controller.window.current_page_id == PageId.POSITION_GUIDANCE
    )
    controller.dispatch("START_ACQUISITION")
    assert controller.window.current_page_id == PageId.ACQUIRING
    controller.dispatch("STOP_SCREENING")
    assert controller.window.current_page_id == PageId.RESULT
    controller.dispatch("RETRY_SCREENING")
    assert controller.window.current_page_id == PageId.POSITION_GUIDANCE


def test_report_actions_use_the_selected_version_through_coordinator(qtbot) -> None:
    coordinator = _Coordinator()
    destination = Path("/tmp/masked-basic-v1.pdf")
    controller = ApplicationController(
        coordinator,
        export_destination=lambda: destination,
    )
    qtbot.addWidget(controller.window)
    coordinator._state = WorkflowState(step=ScreeningStep.BASIC_REPORT)
    controller.refresh()

    controller.dispatch("VIEW_BASIC_REPORT")
    controller.dispatch("EXPORT_PDF")
    controller.dispatch("PRINT_REPORT")

    assert controller.window.current_page_id == PageId.REPORT_PREVIEW
    assert coordinator.exports == [destination]
    assert coordinator.print_count == 1


def test_device_events_refresh_result_and_recovery_pages(qtbot) -> None:
    coordinator = _Coordinator()
    controller = ApplicationController(coordinator)
    qtbot.addWidget(controller.window)
    coordinator._state = WorkflowState(step=ScreeningStep.ACQUIRING)
    controller.refresh()

    controller.on_acquisition_completed()
    assert controller.window.current_page_id == PageId.RESULT

    coordinator._state = WorkflowState(step=ScreeningStep.ACQUIRING)
    controller.refresh()
    controller.on_device_disconnected("technical stack")
    assert controller.window.current_page_id == PageId.RESULT


def test_start_next_action_returns_to_subject_identification(qtbot) -> None:
    coordinator = _Coordinator()
    controller = ApplicationController(coordinator)
    qtbot.addWidget(controller.window)
    coordinator._state = WorkflowState(step=ScreeningStep.BASIC_REPORT)
    controller.refresh()

    controller.dispatch("START_NEXT_SCREENING")

    assert controller.window.current_page_id == PageId.SUBJECT_IDENTIFICATION
