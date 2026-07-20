from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QCheckBox, QComboBox, QLineEdit, QLabel

from client.app.controller import ApplicationController
from client.app.pages import PageId
from client.workflow.consent import ConsentPolicy, ConsentReceipt, ConsentWorkflow
from client.workflow.models import WorkflowState
from client.workflow.participant import (
    AnalysisProfile,
    ParticipantWorkflow,
    SubjectResolution,
    SubjectResolutionStatus,
    SubjectSummary,
)
from client.workflow.state_machine import ScreeningStep


class _Coordinator:
    def __init__(self) -> None:
        self._state = WorkflowState(ScreeningStep.HOME)
        self.bindings: list[tuple[str, str]] = []

    @property
    def state(self) -> WorkflowState:
        return self._state

    def start_new_screening(self) -> None:
        self._state = WorkflowState(ScreeningStep.SUBJECT_IDENTIFICATION)

    def confirm_subject(self) -> None:
        self._state = WorkflowState(ScreeningStep.PROFILE_DETAILS)

    def complete_profile(self) -> None:
        self._state = WorkflowState(ScreeningStep.CONSENT_CONFIRMATION)

    def bind_participant(self, *, subject_uuid: str, consent_record_id: str) -> None:
        self.bindings.append((subject_uuid, consent_record_id))

    def confirm_consent(self) -> None:
        self._state = WorkflowState(ScreeningStep.PREFLIGHT)

    def run_preflight(self) -> bool:
        self._state = WorkflowState(ScreeningStep.POSITION_GUIDANCE)
        return True

    def start_acquisition(self) -> bool:
        return False

    def stop_acquisition(self) -> bool:
        return False

    def retry_screening(self) -> None: ...

    def export_current_report(self, destination: Path) -> None:
        _ = destination

    def print_current_report(self) -> None: ...

    def complete_acquisition(self) -> None: ...

    def handle_device_disconnect(self, *, technical_detail: str) -> None:
        _ = technical_detail

    def start_next_screening(self) -> None: ...


class _Subjects:
    def __init__(self, resolution: SubjectResolution) -> None:
        self.resolution = resolution
        self.updated: list[AnalysisProfile] = []

    def resolve(self, request):
        _ = request
        return self.resolution

    def create(self, request):
        _ = request
        return SubjectSummary("anonymous-1", "tenant-a", "临时001")

    def update_profile(self, *, tenant_id, subject_uuid, profile) -> None:
        _ = tenant_id, subject_uuid
        self.updated.append(profile)


class _Audit:
    def record_subject_access(self, **kwargs) -> None:
        _ = kwargs


class _Consents:
    def __init__(self) -> None:
        self.created = []

    def find_valid(self, **kwargs):
        _ = kwargs
        return None

    def create(self, request):
        self.created.append(request)
        return ConsentReceipt(
            consent_record_id="consent-1",
            tenant_id=request.tenant_id,
            subject_uuid=request.subject_uuid,
            policy_version=request.policy_version,
            purpose_codes=request.purpose_codes,
            data_categories=request.data_categories,
        )


POLICY = ConsentPolicy(
    policy_version="privacy/1",
    purpose_codes=("SCREENING_SERVICE",),
    data_categories=("PRESSURE_RAW", "ANALYSIS_PROFILE"),
)


def _controller(resolution: SubjectResolution) -> tuple[ApplicationController, _Coordinator, _Subjects, _Consents]:
    coordinator = _Coordinator()
    subjects = _Subjects(resolution)
    consents = _Consents()
    participant = ParticipantWorkflow(
        tenant_id="tenant-a",
        issuer="site-a",
        subjects=subjects,
        audit=_Audit(),
    )
    consent = ConsentWorkflow(
        tenant_id="tenant-a",
        terminal_id="terminal-a",
        consents=consents,
    )
    return (
        ApplicationController(
            coordinator,
            participant=participant,
            consent=consent,
            consent_policy=POLICY,
        ),
        coordinator,
        subjects,
        consents,
    )


def test_found_subject_profile_and_consent_are_bound_before_preflight(qtbot) -> None:
    subject = SubjectSummary("subject-1", "tenant-a", "**1234")
    controller, coordinator, subjects, consents = _controller(
        SubjectResolution(SubjectResolutionStatus.FOUND, (subject,))
    )
    qtbot.addWidget(controller.window)
    controller.dispatch("START_NEW_SCREENING")
    page = controller.window.page_widget(PageId.SUBJECT_IDENTIFICATION)
    page.findChild(QLineEdit, "subjectExternalIdInput").setText("MR-1234")

    controller.dispatch("LOOKUP_SUBJECT")

    assert "已找到" in page.findChild(QLabel, "subjectMatchSummary").text()
    controller.dispatch("CONFIRM_SUBJECT")
    profile_page = controller.window.page_widget(PageId.PROFILE)
    height_state = profile_page.findChild(QComboBox, "heightState")
    height_state.setCurrentIndex(height_state.findData("PROVIDED"))
    profile_page.findChild(QLineEdit, "heightInput").setText("168.5")
    controller.dispatch("SAVE_PROFILE")

    assert controller.window.current_page_id == PageId.CONSENT
    assert subjects.updated[0].height_cm.value == 168.5
    consent_page = controller.window.page_widget(PageId.CONSENT)
    consent_page.findChild(QCheckBox, "requiredConsent").setChecked(True)
    consent_page.findChild(QCheckBox, "researchConsent").setChecked(False)
    controller.dispatch("CONFIRM_CONSENT")

    assert coordinator.bindings == [("subject-1", "consent-1")]
    assert consents.created[0].purpose_codes == ("SCREENING_SERVICE",)
    qtbot.waitUntil(
        lambda: controller.window.current_page_id == PageId.POSITION_GUIDANCE
    )


def test_required_consent_decline_stays_on_consent_with_plain_error(qtbot) -> None:
    controller, coordinator, _, consents = _controller(
        SubjectResolution(SubjectResolutionStatus.NOT_FOUND)
    )
    qtbot.addWidget(controller.window)
    controller.dispatch("START_NEW_SCREENING")
    controller.dispatch("CREATE_ANONYMOUS_SUBJECT")
    controller.dispatch("SKIP_PROFILE")

    controller.dispatch("CONFIRM_CONSENT")

    assert controller.window.current_page_id == PageId.CONSENT
    assert "必要处理" in controller.window.error_text
    assert coordinator.bindings == []
    assert consents.created == []


def test_conflicting_identifier_cannot_advance_or_auto_merge(qtbot) -> None:
    controller, _, _, _ = _controller(
        SubjectResolution(
            SubjectResolutionStatus.CONFLICT,
            (
                SubjectSummary("subject-1", "tenant-a", "**1234"),
                SubjectSummary("subject-2", "tenant-a", "**1234"),
            ),
        )
    )
    qtbot.addWidget(controller.window)
    controller.dispatch("START_NEW_SCREENING")
    page = controller.window.page_widget(PageId.SUBJECT_IDENTIFICATION)
    page.findChild(QLineEdit, "subjectExternalIdInput").setText("MR-1234")
    controller.dispatch("LOOKUP_SUBJECT")

    controller.dispatch("CONFIRM_SUBJECT")

    assert controller.window.current_page_id == PageId.SUBJECT_IDENTIFICATION
    assert "多个" in controller.window.error_text
