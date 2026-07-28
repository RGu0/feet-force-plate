from __future__ import annotations

from client.workflow.coordinator import ScreeningCoordinator
from client.workflow.models import PreflightCheck, PreflightSummary, QualityOutcome, QualityResult
from client.workflow.protocol import ProtocolSnapshot
from client.workflow.state_machine import ScreeningStep


class _Preflight:
    def run_preflight(self) -> PreflightSummary:
        return PreflightSummary((PreflightCheck("all", True),))


class _Sessions:
    def __init__(self) -> None:
        self.protocols: list[ProtocolSnapshot] = []

    def create_session(self, participant, protocol: ProtocolSnapshot) -> str:
        _ = participant
        self.protocols.append(protocol)
        return "session-1"

    def mark_incomplete(self, session_id: str) -> None:
        _ = session_id

    def finalize(self, session_id: str) -> None:
        _ = session_id


class _Acquisition:
    def __init__(self) -> None:
        self.started: list[str] = []

    def start(self, session_id: str) -> None:
        self.started.append(session_id)

    def stop(self, session_id: str) -> None:
        _ = session_id


class _Analysis:
    def analyze(self, session_id: str) -> QualityResult:
        _ = session_id
        return QualityResult(QualityOutcome.VALID)


class _Reports:
    def create_basic_report(self, session_id: str) -> tuple[str, int]:
        _ = session_id
        return ("report-1", 1)

    def export_pdf(self, *args) -> None:
        _ = args

    def print_report(self, *args) -> None:
        _ = args


class _Telemetry:
    def record_error(self, **kwargs) -> None:
        _ = kwargs


def _coordinator() -> tuple[ScreeningCoordinator, _Sessions, _Acquisition]:
    sessions = _Sessions()
    acquisition = _Acquisition()
    coordinator = ScreeningCoordinator(
        preflight=_Preflight(),
        sessions=sessions,
        acquisition=acquisition,
        analysis=_Analysis(),
        reports=_Reports(),
        telemetry=_Telemetry(),
    )
    coordinator.bind_participant(
        subject_uuid="subject-1",
        consent_record_id="consent-1",
    )
    coordinator.start_new_screening()
    coordinator.confirm_subject()
    coordinator.complete_profile()
    coordinator.confirm_consent()
    coordinator.run_preflight()
    coordinator.enter_position_guidance()
    return coordinator, sessions, acquisition


def test_stable_position_waits_for_explicit_start_and_passes_protocol_snapshot() -> None:
    coordinator, sessions, acquisition = _coordinator()

    first = coordinator.observe_position(
        now_seconds=10.0,
        contact_ready=True,
        in_valid_area=True,
    )
    ready = coordinator.observe_position(
        now_seconds=13.0,
        contact_ready=True,
        in_valid_area=True,
    )

    assert first.countdown_seconds == 3
    assert ready.manual_start_allowed
    assert not ready.auto_start
    assert coordinator.state.step is ScreeningStep.POSITION_GUIDANCE
    assert acquisition.started == []
    assert sessions.protocols == []

    assert coordinator.start_acquisition()
    assert coordinator.state.step is ScreeningStep.ACQUIRING
    assert acquisition.started == ["session-1"]
    assert sessions.protocols == [
        ProtocolSnapshot(
            protocol_id="standard-static-bilateral",
                protocol_version="v1-replay-debug/1.0.0",
                planned_duration_seconds=80,
                quality_gate_id="static-basic-quality",
                quality_gate_version="1.0.0-pilot",
                stage_ids=(
                    "BILATERAL_EYES_OPEN",
                    "BILATERAL_EYES_CLOSED",
                    "SEMI_TANDEM_LEFT_FORWARD",
                    "SEMI_TANDEM_RIGHT_FORWARD",
                ),
        )
    ]


def test_manual_start_is_blocked_until_minimum_contact_and_valid_area() -> None:
    coordinator, sessions, _ = _coordinator()

    assert not coordinator.start_acquisition()
    coordinator.observe_position(
        now_seconds=0.0,
        contact_ready=True,
        in_valid_area=False,
    )
    assert not coordinator.start_acquisition()
    coordinator.observe_position(
        now_seconds=1.0,
        contact_ready=True,
        in_valid_area=True,
    )
    assert not coordinator.start_acquisition()
    coordinator.observe_position(
        now_seconds=4.0,
        contact_ready=True,
        in_valid_area=True,
    )

    assert coordinator.start_acquisition()
    assert len(sessions.protocols) == 1


def test_protocol_duration_automatically_finishes_local_processing_and_basic_report() -> None:
    coordinator, _, _ = _coordinator()
    coordinator.observe_position(
        now_seconds=0.0,
        contact_ready=True,
        in_valid_area=True,
    )
    coordinator.observe_position(
        now_seconds=3.0,
        contact_ready=True,
        in_valid_area=True,
    )
    assert coordinator.start_acquisition()

    remaining = coordinator.observe_acquisition_elapsed(elapsed_seconds=5)

    assert remaining == 15
    assert coordinator.state.remaining_seconds == 15
    finished = coordinator.observe_acquisition_elapsed(elapsed_seconds=20)
    assert finished == 0
    assert coordinator.state.step is ScreeningStep.POSITION_GUIDANCE
