from __future__ import annotations

from client.workflow.coordinator import ScreeningCoordinator
from client.workflow.models import PreflightCheck, PreflightSummary, QualityOutcome, QualityResult
from client.workflow.state_machine import ScreeningStep


class _Preflight:
    def run_preflight(self) -> PreflightSummary:
        return PreflightSummary((PreflightCheck("ready", True),))


class _Sessions:
    def __init__(self) -> None:
        self.finalized: list[str] = []
        self.stages: list[str] = []

    def create_session(self, _context, _protocol) -> str:
        return "physical-session-1"

    def mark_incomplete(self, _session_id: str) -> None:
        raise AssertionError("continuous capture must not be marked incomplete")

    def mark_stage_complete(self, _session_id: str, stage_id: str) -> None:
        self.stages.append(stage_id)

    def finalize(self, session_id: str) -> None:
        self.finalized.append(session_id)


class _Acquisition:
    continuous_stage_capture = True

    def __init__(self) -> None:
        self.started: list[str] = []
        self.finished: list[str] = []

    def start_stage(self, session_id, _stage) -> None:
        self.started.append(session_id)

    def finish(self, session_id: str) -> None:
        self.finished.append(session_id)

    def stop(self, _session_id: str) -> None:
        pass


class _AnalysisAndReports:
    def analyze(self, _session_id: str) -> QualityResult:
        return QualityResult(QualityOutcome.VALID)

    def create_basic_report(self, _session_id: str) -> tuple[str, int]:
        return ("report-1", 1)

    def export_pdf(self, *_args) -> None:
        pass

    def print_report(self, *_args) -> None:
        pass


class _Telemetry:
    def record_error(self, **_event) -> None:
        raise AssertionError("unexpected workflow error")


def test_continuous_live_capture_keeps_one_hardware_session_across_all_four_ui_stages() -> None:
    sessions, acquisition, reports = _Sessions(), _Acquisition(), _AnalysisAndReports()
    coordinator = ScreeningCoordinator(
        preflight=_Preflight(), sessions=sessions, acquisition=acquisition,
        analysis=reports, reports=reports, telemetry=_Telemetry(),
    )
    coordinator.bind_participant(subject_uuid="subject-1", consent_record_id="consent-1")
    coordinator.start_new_screening()
    coordinator.confirm_subject()
    coordinator.complete_profile()
    coordinator.confirm_consent()
    assert coordinator.run_preflight()
    assert coordinator.enter_position_guidance()
    coordinator.observe_position(now_seconds=0.0, contact_ready=True, in_valid_area=True)
    coordinator.observe_position(now_seconds=3.0, contact_ready=True, in_valid_area=True)
    assert coordinator.start_acquisition()

    for _ in range(4):
        coordinator.observe_acquisition_elapsed(elapsed_seconds=20)

    assert acquisition.started == ["physical-session-1"]
    assert len(sessions.stages) == 4
    assert acquisition.finished == ["physical-session-1"]
    assert sessions.finalized == []
    assert coordinator.state.step is ScreeningStep.FINALIZING

    coordinator.complete_acquisition()

    assert sessions.finalized == ["physical-session-1"]
    assert coordinator.state.step is ScreeningStep.BASIC_REPORT
