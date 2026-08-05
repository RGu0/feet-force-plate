from dataclasses import replace

from client.workflow.coordinator import ScreeningCoordinator
from client.workflow.models import (
    ClientAction,
    ClientError,
    PreflightCheck,
    PreflightSummary,
    QualityOutcome,
    QualityResult,
)
from client.workflow.protocol import StartCondition, default_standard_protocol
from client.workflow.state_machine import ScreeningStep


class _Preflight:
    def run_preflight(self):
        return PreflightSummary((PreflightCheck("fixture", True),))


class _Sessions:
    def __init__(self):
        self.created = []
        self.finalized = []
        self.completed_stages = []
        self.incomplete = []

    def create_session(self, context, protocol):
        self.created.append((context, protocol))
        return "replay-session-1"

    def mark_incomplete(self, session_id):
        self.incomplete.append(session_id)

    def finalize(self, session_id):
        self.finalized.append(session_id)

    def mark_stage_complete(self, session_id, stage_id):
        self.completed_stages.append((session_id, stage_id))


class _Acquisition:
    def __init__(self):
        self.stages = []
        self.stopped = []

    def start(self, session_id):
        raise AssertionError(session_id)

    def start_stage(self, session_id, stage):
        self.stages.append((session_id, stage.stage_id))

    def stop(self, session_id):
        self.stopped.append(session_id)


class _AsyncAcquisition(_Acquisition):
    def __init__(self):
        super().__init__()
        self.finished = []

    def finish(self, session_id):
        self.finished.append(session_id)


class _Analysis:
    def analyze(self, session_id):
        assert session_id == "replay-session-1"
        return QualityResult(QualityOutcome.VALID)


class _InvalidAnalysis:
    def analyze(self, session_id):
        assert session_id == "replay-session-1"
        return QualityResult(QualityOutcome.INVALID)


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


class _CollectingTelemetry:
    def __init__(self):
        self.errors = []

    def record_error(self, **kwargs):
        self.errors.append(kwargs)


def _ready_coordinator():
    sessions = _Sessions()
    acquisition = _Acquisition()
    telemetry = _CollectingTelemetry()
    coordinator = ScreeningCoordinator(
        preflight=_Preflight(), sessions=sessions, acquisition=acquisition,
        analysis=_Analysis(), reports=_Reports(), telemetry=telemetry,
        data_source_mode="REPLAY_DEBUG",
    )
    coordinator.bind_participant(subject_uuid="subject-1", consent_record_id="consent-1")
    coordinator.start_new_screening()
    coordinator.confirm_subject()
    coordinator.complete_profile()
    coordinator.confirm_consent()
    assert coordinator.run_preflight()
    assert coordinator.enter_position_guidance()
    return coordinator, sessions, acquisition, telemetry


def _coordinator_after_first_stage():
    coordinator, sessions, acquisition, telemetry = _ready_coordinator()
    assert coordinator.start_acquisition()
    coordinator.observe_acquisition_elapsed(elapsed_seconds=20)
    return coordinator, sessions, acquisition, telemetry


def test_retryable_second_stage_failure_preserves_first_stage_and_session() -> None:
    coordinator, sessions, acquisition, telemetry = _coordinator_after_first_stage()
    session_id = coordinator.state.session_id
    assert coordinator.start_acquisition()

    coordinator.handle_stage_capture_failure(technical_detail="serial disconnected")

    assert coordinator.state.step is ScreeningStep.POSITION_GUIDANCE
    assert coordinator.state.stage_index == 2
    assert coordinator.state.session_id == session_id
    assert coordinator.state.notice == "本段采集中断，请重新连接设备并重测本段"
    assert sessions.completed_stages == [
        ("replay-session-1", "BILATERAL_EYES_OPEN")
    ]
    assert sessions.incomplete == []
    assert acquisition.stopped == ["replay-session-1"]
    assert telemetry.errors == [
        {
            "code": "E-ACQ-004",
            "session_id": "replay-session-1",
            "technical_detail": "serial disconnected",
        }
    ]
    assert coordinator.start_acquisition()
    assert acquisition.stages[-1][1] == "BILATERAL_EYES_CLOSED"


def test_blocked_manual_start_asks_operator_to_confirm_position_and_safety() -> None:
    protocol = replace(
        default_standard_protocol(),
        start_condition=StartCondition(stable_hold_seconds=3),
    )
    coordinator = ScreeningCoordinator(
        preflight=_Preflight(), sessions=_Sessions(), acquisition=_Acquisition(),
        analysis=_Analysis(), reports=_Reports(), telemetry=_Telemetry(),
        protocol=protocol,
    )
    coordinator.bind_participant(subject_uuid="subject-1", consent_record_id="consent-1")
    coordinator.start_new_screening()
    coordinator.confirm_subject()
    coordinator.complete_profile()
    coordinator.confirm_consent()
    assert coordinator.run_preflight()
    assert coordinator.enter_position_guidance()

    assert not coordinator.start_acquisition()

    assert coordinator.state.error.operator_message == "请由操作员确认站位和安全后开始本段"
    assert "站稳" not in coordinator.state.error.operator_message


def test_finalizing_storage_failure_closes_the_whole_session() -> None:
    sessions = _Sessions()
    acquisition = _AsyncAcquisition()
    coordinator = ScreeningCoordinator(
        preflight=_Preflight(), sessions=sessions, acquisition=acquisition,
        analysis=_Analysis(), reports=_Reports(), telemetry=_CollectingTelemetry(),
    )
    coordinator.bind_participant(subject_uuid="subject-1", consent_record_id="consent-1")
    coordinator.start_new_screening()
    coordinator.confirm_subject()
    coordinator.complete_profile()
    coordinator.confirm_consent()
    assert coordinator.run_preflight()
    assert coordinator.enter_position_guidance()
    for _ in range(4):
        assert coordinator.start_acquisition()
        coordinator.observe_acquisition_elapsed(elapsed_seconds=20)
    assert coordinator.state.step is ScreeningStep.FINALIZING

    coordinator.handle_hardware_failure(
        error=ClientError(
            code="E-DAT-101",
            operator_message="硬件数据未通过完整性检查，本次检测未完成",
            action=ClientAction.RETRY_SCREENING,
        )
    )

    assert coordinator.state.step is ScreeningStep.INCOMPLETE
    assert sessions.incomplete == ["replay-session-1"]


def test_final_invalid_result_does_not_tell_operator_to_stand_still() -> None:
    coordinator = ScreeningCoordinator(
        preflight=_Preflight(), sessions=_Sessions(), acquisition=_Acquisition(),
        analysis=_InvalidAnalysis(), reports=_Reports(), telemetry=_Telemetry(),
    )
    coordinator.bind_participant(subject_uuid="subject-1", consent_record_id="consent-1")
    coordinator.start_new_screening()
    coordinator.confirm_subject()
    coordinator.complete_profile()
    coordinator.confirm_consent()
    assert coordinator.run_preflight()
    assert coordinator.enter_position_guidance()
    for _ in range(4):
        assert coordinator.start_acquisition()
        coordinator.observe_acquisition_elapsed(elapsed_seconds=20)

    assert coordinator.state.step is ScreeningStep.RETRY_REQUIRED
    assert coordinator.state.error.operator_message == "本次检测未通过质量检查，请重新检测"
    assert "站稳" not in coordinator.state.error.operator_message


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
    assert sessions.incomplete == []
    assert sessions.completed_stages == [
        ("replay-session-1", "BILATERAL_EYES_OPEN"),
        ("replay-session-1", "BILATERAL_EYES_CLOSED"),
        ("replay-session-1", "SEMI_TANDEM_LEFT_FORWARD"),
        ("replay-session-1", "SEMI_TANDEM_RIGHT_FORWARD"),
    ]
    assert coordinator.state.step is ScreeningStep.BASIC_REPORT
