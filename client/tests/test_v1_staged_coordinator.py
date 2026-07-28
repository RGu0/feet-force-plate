from client.workflow.coordinator import ScreeningCoordinator
from client.workflow.models import PreflightCheck, PreflightSummary, QualityOutcome, QualityResult
from client.workflow.state_machine import ScreeningStep


class _Preflight:
    def run_preflight(self):
        return PreflightSummary((PreflightCheck("fixture", True),))


class _Sessions:
    def __init__(self):
        self.created = []
        self.finalized = []
        self.completed_stages = []

    def create_session(self, context, protocol):
        self.created.append((context, protocol))
        return "replay-session-1"

    def mark_incomplete(self, session_id):
        raise AssertionError(session_id)

    def finalize(self, session_id):
        self.finalized.append(session_id)

    def mark_stage_complete(self, session_id, stage_id):
        self.completed_stages.append((session_id, stage_id))


class _Acquisition:
    def __init__(self):
        self.stages = []

    def start(self, session_id):
        raise AssertionError(session_id)

    def start_stage(self, session_id, stage):
        self.stages.append((session_id, stage.stage_id))

    def stop(self, session_id):
        _ = session_id


class _Analysis:
    def analyze(self, session_id):
        assert session_id == "replay-session-1"
        return QualityResult(QualityOutcome.VALID)


class _Reports:
    def create_basic_report(self, session_id):
        assert session_id == "replay-session-1"
        return "debug-report-1", 1

    def export_pdf(self, *args):
        _ = args

    def print_report(self, *args):
        _ = args


class _Telemetry:
    def record_error(self, **kwargs):
        raise AssertionError(kwargs)


def test_four_stage_protocol_returns_to_guidance_until_final_stage() -> None:
    sessions = _Sessions()
    acquisition = _Acquisition()
    coordinator = ScreeningCoordinator(
        preflight=_Preflight(), sessions=sessions, acquisition=acquisition,
        analysis=_Analysis(), reports=_Reports(), telemetry=_Telemetry(),
        data_source_mode="REPLAY_DEBUG",
    )
    coordinator.bind_participant(subject_uuid="subject-1", consent_record_id="consent-1")
    coordinator.start_new_screening()
    coordinator.confirm_subject()
    coordinator.complete_profile()
    coordinator.confirm_consent()
    assert coordinator.run_preflight()
    assert coordinator.state.step is ScreeningStep.PREFLIGHT
    assert coordinator.state.preflight_ready
    assert coordinator.enter_position_guidance()
    guidance = coordinator.state
    assert guidance.stage_index == 1
    assert guidance.stage_count == 4
    assert guidance.stage_title == "第一段：并足睁眼"

    for expected_index in range(4):
        stage_started_at = float(expected_index * 10)
        coordinator.observe_position(
            now_seconds=stage_started_at, contact_ready=True, in_valid_area=True
        )
        coordinator.observe_position(
            now_seconds=stage_started_at + 3,
            contact_ready=True,
            in_valid_area=True,
        )
        assert coordinator.state.step is ScreeningStep.POSITION_GUIDANCE
        assert coordinator.start_acquisition()
        state = coordinator.state
        assert state.stage_index == expected_index + 1
        assert state.stage_count == 4
        assert state.stage_remaining_seconds == 20
        assert state.data_source_mode == "REPLAY_DEBUG"
        coordinator.observe_acquisition_elapsed(elapsed_seconds=20)
        if expected_index < 3:
            assert coordinator.state.step is ScreeningStep.POSITION_GUIDANCE

    assert acquisition.stages == [
        ("replay-session-1", "BILATERAL_EYES_OPEN"),
        ("replay-session-1", "BILATERAL_EYES_CLOSED"),
        ("replay-session-1", "SEMI_TANDEM_LEFT_FORWARD"),
        ("replay-session-1", "SEMI_TANDEM_RIGHT_FORWARD"),
    ]
    assert len(sessions.created) == 1
    assert sessions.finalized == ["replay-session-1"]
    assert sessions.completed_stages == [
        ("replay-session-1", "BILATERAL_EYES_OPEN"),
        ("replay-session-1", "BILATERAL_EYES_CLOSED"),
        ("replay-session-1", "SEMI_TANDEM_LEFT_FORWARD"),
        ("replay-session-1", "SEMI_TANDEM_RIGHT_FORWARD"),
    ]
    assert coordinator.state.step is ScreeningStep.BASIC_REPORT
