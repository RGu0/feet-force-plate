from __future__ import annotations

from client.workflow.coordinator import ScreeningCoordinator
from client.workflow.models import (
    PreflightCheck,
    PreflightSummary,
    QualityOutcome,
    QualityResult,
)
from client.workflow.state_machine import ScreeningStep


EXPECTED_STAGE_IDS = (
    "BILATERAL_EYES_OPEN",
    "BILATERAL_EYES_CLOSED",
    "SEMI_TANDEM_LEFT_FORWARD",
    "SEMI_TANDEM_RIGHT_FORWARD",
)


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
        raise AssertionError("stage handoff must not mark the session incomplete")

    def mark_stage_complete(self, _session_id: str, stage_id: str) -> None:
        self.stages.append(stage_id)

    def finalize(self, session_id: str) -> None:
        self.finalized.append(session_id)


class _Acquisition:
    continuous_stage_capture = True

    def __init__(self) -> None:
        self.started: list[tuple[str, str]] = []
        self.finished: list[str] = []

    def start_stage(self, session_id, stage) -> None:
        self.started.append((session_id, stage.stage_id))

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


def _ready_live_coordinator() -> tuple[ScreeningCoordinator, _Acquisition]:
    acquisition = _Acquisition()
    coordinator = ScreeningCoordinator(
        preflight=_Preflight(),
        sessions=_Sessions(),
        acquisition=acquisition,
        analysis=_AnalysisAndReports(),
        reports=_AnalysisAndReports(),
        telemetry=_Telemetry(),
    )
    coordinator.bind_participant(
        subject_uuid="subject-1", consent_record_id="consent-1"
    )
    coordinator.start_new_screening()
    coordinator.confirm_subject()
    coordinator.complete_profile()
    coordinator.confirm_consent()
    assert coordinator.run_preflight()
    assert coordinator.enter_position_guidance()
    return coordinator, acquisition


def test_each_live_stage_requires_guidance_and_a_new_operator_start() -> None:
    coordinator, acquisition = _ready_live_coordinator()

    for index, expected_stage in enumerate(EXPECTED_STAGE_IDS):
        assert coordinator.state.step is ScreeningStep.POSITION_GUIDANCE
        assert coordinator.state.stage_index == index + 1
        assert coordinator.start_acquisition()
        assert acquisition.started[-1] == ("physical-session-1", expected_stage)
        coordinator.observe_acquisition_elapsed(elapsed_seconds=20)

    assert coordinator.state.step is ScreeningStep.FINALIZING
    assert len(acquisition.started) == 4
    assert acquisition.finished == ["physical-session-1"]
