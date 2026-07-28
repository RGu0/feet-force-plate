from __future__ import annotations

from pathlib import Path

from .models import (
    AnalysisStatus,
    ClientAction,
    ClientError,
    LifecycleStatus,
    PreflightCheck,
    QualityOutcome,
    ReportStatus,
    ScreeningParticipantContext,
    SessionValidity,
    UploadStatus,
    WorkflowState,
)
from .ports import (
    AcquisitionPort,
    AnalysisPort,
    PreflightPort,
    ReportPort,
    SessionPort,
    TelemetryPort,
)
from .protocol import (
    PositionGuidanceController,
    PositionGuidanceState,
    ScreeningProtocol,
    default_standard_protocol,
)
from .state_machine import ScreeningStep, SessionStateMachine


class ScreeningCoordinator:
    def __init__(
        self,
        *,
        preflight: PreflightPort,
        sessions: SessionPort,
        acquisition: AcquisitionPort,
        analysis: AnalysisPort,
        reports: ReportPort,
        telemetry: TelemetryPort,
        protocol: ScreeningProtocol | None = None,
        data_source_mode: str = "LIVE",
    ) -> None:
        self._machine = SessionStateMachine()
        self._preflight = preflight
        self._sessions = sessions
        self._acquisition = acquisition
        self._analysis = analysis
        self._reports = reports
        self._telemetry = telemetry
        self._protocol = protocol or default_standard_protocol()
        self._data_source_mode = data_source_mode
        self._position_guidance = PositionGuidanceController(self._protocol)
        self._session_id: str | None = None
        self._remaining_seconds: int | None = None
        self._participant_context: ScreeningParticipantContext | None = None
        self._lifecycle_status = LifecycleStatus.DRAFT
        self._validity = SessionValidity.UNKNOWN
        self._upload_status = UploadStatus.LOCAL_ONLY
        self._analysis_status = AnalysisStatus.NOT_REQUESTED
        self._report_status = ReportStatus.NOT_AVAILABLE
        self._report_id: str | None = None
        self._report_version: int | None = None
        self._error: ClientError | None = None
        self._notice: str | None = None
        self._preflight_checks: tuple[PreflightCheck, ...] = ()
        self._preflight_ready = False
        self._stage_index = 0
        self._position_guidance.set_stage(self._protocol.stages[self._stage_index])

    @property
    def state(self) -> WorkflowState:
        return WorkflowState(
            step=self._machine.step,
            session_id=self._session_id,
            lifecycle_status=self._lifecycle_status,
            validity=self._validity,
            upload_status=self._upload_status,
            analysis_status=self._analysis_status,
            report_status=self._report_status,
            report_id=self._report_id,
            report_version=self._report_version,
            error=self._error,
            notice=self._notice,
            preflight_checks=self._preflight_checks,
            preflight_ready=self._preflight_ready,
            position_guidance=(
                self._position_guidance.state
                if self._machine.step is ScreeningStep.POSITION_GUIDANCE
                else None
            ),
            acquisition_instruction=(
                self._current_stage.acquisition_text
                if self._machine.step is ScreeningStep.ACQUIRING
                else None
            ),
            planned_duration_seconds=(
                self._current_stage.duration_seconds
                if self._machine.step is ScreeningStep.ACQUIRING
                else None
            ),
            remaining_seconds=(
                self._remaining_seconds
                if self._machine.step is ScreeningStep.ACQUIRING
                else None
            ),
            stage_index=(
                self._stage_index + 1
                if self._machine.step
                in {ScreeningStep.POSITION_GUIDANCE, ScreeningStep.ACQUIRING}
                else None
            ),
            stage_count=len(self._protocol.stages),
            stage_title=(
                self._current_stage.operator_title
                if self._machine.step
                in {ScreeningStep.POSITION_GUIDANCE, ScreeningStep.ACQUIRING}
                else None
            ),
            stage_remaining_seconds=(self._remaining_seconds if self._machine.step is ScreeningStep.ACQUIRING else None),
            data_source_mode=self._data_source_mode,
        )

    def start_new_screening(self) -> None:
        self._transition(ScreeningStep.SUBJECT_IDENTIFICATION)

    def bind_participant(self, *, subject_uuid: str, consent_record_id: str) -> None:
        if not subject_uuid.strip() or not consent_record_id.strip():
            raise ValueError("subject and consent identifiers are required")
        self._participant_context = ScreeningParticipantContext(
            subject_uuid=subject_uuid,
            consent_record_id=consent_record_id,
        )

    def confirm_subject(self) -> None:
        self._transition(ScreeningStep.PROFILE_DETAILS)

    def complete_profile(self) -> None:
        self._transition(ScreeningStep.CONSENT_CONFIRMATION)

    def confirm_consent(self) -> None:
        self._transition(ScreeningStep.PREFLIGHT)
        self._lifecycle_status = LifecycleStatus.PREFLIGHT
        self._preflight_checks = ()
        self._preflight_ready = False

    def run_preflight(self) -> bool:
        if self._machine.step is not ScreeningStep.PREFLIGHT:
            return False
        summary = self._preflight.run_preflight()
        self._preflight_checks = summary.checks
        self._preflight_ready = False
        failure = summary.first_failure
        if failure is not None:
            self._error = ClientError(
                code=failure.error_code or "E-SYS-001",
                operator_message=failure.operator_message or "暂时无法开始检测，请重新检查",
                action=ClientAction.RECHECK,
            )
            return False
        self._error = None
        self._preflight_ready = True
        return True

    def enter_position_guidance(self) -> bool:
        if (
            self._machine.step is not ScreeningStep.PREFLIGHT
            or not self._preflight_ready
        ):
            self._error = ClientError(
                code="E-PRE-001",
                operator_message="请先完成本次设备预检",
                action=ClientAction.RECHECK,
            )
            return False
        self._transition(ScreeningStep.POSITION_GUIDANCE)
        self._position_guidance.set_stage(self._current_stage)
        self._position_guidance.reset()
        return True

    def observe_position(
        self,
        *,
        now_seconds: float,
        contact_ready: bool,
        in_valid_area: bool,
    ) -> PositionGuidanceState:
        if self._machine.step is not ScreeningStep.POSITION_GUIDANCE:
            return self._position_guidance.state
        state = self._position_guidance.observe(
            now_seconds=now_seconds,
            contact_ready=contact_ready,
            in_valid_area=in_valid_area,
        )
        return state

    def start_acquisition(self) -> bool:
        if self._machine.step is not ScreeningStep.POSITION_GUIDANCE:
            return False
        if not self._position_guidance.state.manual_start_allowed:
            self._error = ClientError(
                code="E-POS-001",
                operator_message="请站到压力垫中央并保持站稳",
                action=ClientAction.RECHECK,
            )
            return False
        if self._participant_context is None:
            self._error = ClientError(
                code="E-AUT-001",
                operator_message="请先确认受试者和授权，再开始检测",
                action=ClientAction.RECHECK,
            )
            return False
        if self._session_id is None:
            try:
                session_id = self._sessions.create_session(
                    self._participant_context,
                    self._protocol.snapshot(),
                )
            except Exception as exc:
                technical_detail = f"{type(exc).__name__}: {exc}"
                self._telemetry.record_error(
                    code="E-DAT-001",
                    session_id=None,
                    technical_detail=technical_detail,
                )
                self._error = ClientError(
                    code="E-DAT-001",
                    operator_message="暂时无法保存检测数据，请重新检查后再试",
                    action=ClientAction.RECHECK,
                )
                return False
            self._session_id = session_id
        session_id = self._session_id
        self._transition(ScreeningStep.ACQUIRING)
        self._lifecycle_status = LifecycleStatus.ACQUIRING
        self._remaining_seconds = self._current_stage.duration_seconds
        try:
            start_stage = getattr(self._acquisition, "start_stage", None)
            if callable(start_stage):
                start_stage(session_id, self._current_stage)
            else:
                self._acquisition.start(session_id)
        except Exception as exc:
            technical_detail = f"{type(exc).__name__}: {exc}"
            self._telemetry.record_error(
                code="E-ACQ-001",
                session_id=session_id,
                technical_detail=technical_detail,
            )
            self._sessions.mark_incomplete(session_id)
            self._lifecycle_status = LifecycleStatus.CLOSED
            self._validity = SessionValidity.INCOMPLETE
            self._machine.mark_incomplete()
            self._error = ClientError(
                code="E-ACQ-001",
                operator_message="暂时无法开始检测，请重新检查设备后重试",
                action=ClientAction.RETRY_SCREENING,
            )
            return False
        return True

    def observe_acquisition_elapsed(self, *, elapsed_seconds: int) -> int | None:
        if self._machine.step is not ScreeningStep.ACQUIRING:
            return None
        if elapsed_seconds < 0:
            raise ValueError("elapsed_seconds cannot be negative")
        remaining = max(
            0,
            self._current_stage.duration_seconds - elapsed_seconds,
        )
        self._remaining_seconds = remaining
        if remaining == 0:
            self.complete_stage()
        return remaining

    def handle_device_disconnect(self, *, technical_detail: str) -> None:
        if self._machine.step is not ScreeningStep.ACQUIRING or self._session_id is None:
            return
        self._telemetry.record_error(
            code="E-DEV-002",
            session_id=self._session_id,
            technical_detail=technical_detail,
        )
        self._sessions.mark_incomplete(self._session_id)
        self._lifecycle_status = LifecycleStatus.CLOSED
        self._validity = SessionValidity.INCOMPLETE
        self._machine.mark_incomplete()
        self._error = ClientError(
            code="E-DEV-002",
            operator_message="压力设备连接已中断，本次检测未完成",
            action=ClientAction.RETRY_SCREENING,
        )

    def stop_acquisition(self) -> bool:
        if self._machine.step is not ScreeningStep.ACQUIRING or self._session_id is None:
            return False
        session_id = self._session_id
        self._acquisition.stop(session_id)
        self._sessions.mark_incomplete(session_id)
        self._lifecycle_status = LifecycleStatus.CLOSED
        self._validity = SessionValidity.INCOMPLETE
        self._machine.mark_incomplete()
        self._error = ClientError(
            code="E-ACQ-003",
            operator_message="检测已停止，本次检测未完成",
            action=ClientAction.RETRY_SCREENING,
        )
        return True

    def retry_screening(self) -> None:
        self._machine.retry()
        self._position_guidance.reset()
        self._session_id = None
        self._remaining_seconds = None
        self._lifecycle_status = LifecycleStatus.PREFLIGHT
        self._validity = SessionValidity.UNKNOWN
        self._upload_status = UploadStatus.LOCAL_ONLY
        self._analysis_status = AnalysisStatus.NOT_REQUESTED
        self._report_status = ReportStatus.NOT_AVAILABLE
        self._report_id = None
        self._report_version = None
        self._error = None
        self._notice = None
        self._preflight_checks = ()
        self._preflight_ready = False
        self._stage_index = 0
        self._position_guidance.set_stage(self._current_stage)

    def start_next_screening(self) -> None:
        if self._machine.step is not ScreeningStep.BASIC_REPORT:
            return
        self._machine = SessionStateMachine()
        self._session_id = None
        self._remaining_seconds = None
        self._participant_context = None
        self._lifecycle_status = LifecycleStatus.DRAFT
        self._validity = SessionValidity.UNKNOWN
        self._upload_status = UploadStatus.LOCAL_ONLY
        self._analysis_status = AnalysisStatus.NOT_REQUESTED
        self._report_status = ReportStatus.NOT_AVAILABLE
        self._report_id = None
        self._report_version = None
        self._error = None
        self._notice = None
        self._preflight_checks = ()
        self._preflight_ready = False
        self._stage_index = 0
        self._position_guidance.set_stage(self._current_stage)
        self.start_new_screening()

    def complete_acquisition(self) -> None:
        if self._machine.step is not ScreeningStep.ACQUIRING or self._session_id is None:
            return
        session_id = self._session_id
        self._remaining_seconds = 0
        self._transition(ScreeningStep.FINALIZING)
        self._lifecycle_status = LifecycleStatus.FINALIZING
        self._sessions.finalize(session_id)
        quality = self._analysis.analyze(session_id)
        if quality.outcome is not QualityOutcome.VALID:
            self._validity = SessionValidity.INVALID
            self._lifecycle_status = LifecycleStatus.CLOSED
            self._machine.mark_retry_required()
            self._error = ClientError(
                code="E-DAT-101",
                operator_message="本次检测未完成，请重新站稳后检测",
                action=ClientAction.RETRY_SCREENING,
            )
            return
        self._validity = SessionValidity.VALID
        try:
            report_id, version = self._reports.create_basic_report(session_id)
        except Exception as exc:
            technical_detail = f"{type(exc).__name__}: {exc}"
            self._telemetry.record_error(
                code="E-RPT-001",
                session_id=session_id,
                technical_detail=technical_detail,
            )
            self._lifecycle_status = LifecycleStatus.CLOSED
            self._machine.mark_failed()
            self._error = ClientError(
                code="E-RPT-001",
                operator_message="暂时无法生成基础报告，请联系技术支持",
                action=ClientAction.CONTACT_SUPPORT,
            )
            return
        self._report_status = ReportStatus.BASIC_READY
        self._report_id = report_id
        self._report_version = version
        self._lifecycle_status = LifecycleStatus.CLOSED
        self._transition(ScreeningStep.BASIC_REPORT)

    def complete_stage(self) -> None:
        if self._machine.step is not ScreeningStep.ACQUIRING or self._session_id is None:
            return
        recorder = getattr(self._sessions, "mark_stage_complete", None)
        if callable(recorder):
            try:
                recorder(self._session_id, self._current_stage.stage_id)
            except Exception as exc:
                self._telemetry.record_error(
                    code="E-DAT-102",
                    session_id=self._session_id,
                    technical_detail=f"{type(exc).__name__}: {exc}",
                )
                self._sessions.mark_incomplete(self._session_id)
                self._lifecycle_status = LifecycleStatus.CLOSED
                self._validity = SessionValidity.INCOMPLETE
                self._machine.mark_incomplete()
                self._error = ClientError(
                    code="E-DAT-102",
                    operator_message="本段数据未能完整保存，本次检测已停止",
                    action=ClientAction.RETRY_SCREENING,
                )
                return
        if self._stage_index + 1 < len(self._protocol.stages):
            self._stage_index += 1
            self._remaining_seconds = None
            self._transition(ScreeningStep.POSITION_GUIDANCE)
            self._position_guidance.set_stage(self._current_stage)
            return
        self.complete_acquisition()

    @property
    def _current_stage(self):
        return self._protocol.stages[self._stage_index]

    def export_current_report(self, destination: Path) -> None:
        report_id, version = self._current_report_reference()
        self._reports.export_pdf(report_id, version, destination)

    def print_current_report(self) -> None:
        report_id, version = self._current_report_reference()
        self._reports.print_report(report_id, version)

    def record_upload_status(self, status: UploadStatus) -> None:
        self._upload_status = status

    def record_cloud_failure(self) -> None:
        if self._report_status is not ReportStatus.BASIC_READY:
            return
        self._analysis_status = AnalysisStatus.FAILED
        self._report_status = ReportStatus.CLOUD_FAILED
        self._notice = "基础报告可继续使用，完整分析正在自动重试"

    def _transition(self, target: ScreeningStep) -> None:
        self._machine.transition_to(target)
        self._error = None

    def _current_report_reference(self) -> tuple[str, int]:
        if self._report_id is None or self._report_version is None:
            raise RuntimeError("no report version is selected")
        return self._report_id, self._report_version
