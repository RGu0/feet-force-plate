from __future__ import annotations

from pathlib import Path

from .models import (
    AnalysisStatus,
    ClientAction,
    ClientError,
    LifecycleStatus,
    QualityOutcome,
    ReportStatus,
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
    ) -> None:
        self._machine = SessionStateMachine()
        self._preflight = preflight
        self._sessions = sessions
        self._acquisition = acquisition
        self._analysis = analysis
        self._reports = reports
        self._telemetry = telemetry
        self._session_id: str | None = None
        self._lifecycle_status = LifecycleStatus.DRAFT
        self._validity = SessionValidity.UNKNOWN
        self._upload_status = UploadStatus.LOCAL_ONLY
        self._analysis_status = AnalysisStatus.NOT_REQUESTED
        self._report_status = ReportStatus.NOT_AVAILABLE
        self._report_id: str | None = None
        self._report_version: int | None = None
        self._error: ClientError | None = None
        self._notice: str | None = None

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
        )

    def start_new_screening(self) -> None:
        self._transition(ScreeningStep.SUBJECT_IDENTIFICATION)

    def confirm_subject(self) -> None:
        self._transition(ScreeningStep.PROFILE_DETAILS)

    def complete_profile(self) -> None:
        self._transition(ScreeningStep.CONSENT_CONFIRMATION)

    def confirm_consent(self) -> None:
        self._transition(ScreeningStep.PREFLIGHT)
        self._lifecycle_status = LifecycleStatus.PREFLIGHT

    def run_preflight(self) -> bool:
        summary = self._preflight.run_preflight()
        failure = summary.first_failure
        if failure is not None:
            self._error = ClientError(
                code=failure.error_code or "E-SYS-001",
                operator_message=failure.operator_message or "暂时无法开始检测，请重新检查",
                action=ClientAction.RECHECK,
            )
            return False
        self._transition(ScreeningStep.POSITION_GUIDANCE)
        return True

    def start_acquisition(self) -> bool:
        if self._machine.step is not ScreeningStep.POSITION_GUIDANCE:
            return False
        try:
            session_id = self._sessions.create_session()
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
        self._transition(ScreeningStep.ACQUIRING)
        self._lifecycle_status = LifecycleStatus.ACQUIRING
        try:
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
        self._session_id = None
        self._lifecycle_status = LifecycleStatus.PREFLIGHT
        self._validity = SessionValidity.UNKNOWN
        self._upload_status = UploadStatus.LOCAL_ONLY
        self._analysis_status = AnalysisStatus.NOT_REQUESTED
        self._report_status = ReportStatus.NOT_AVAILABLE
        self._report_id = None
        self._report_version = None
        self._error = None
        self._notice = None

    def start_next_screening(self) -> None:
        if self._machine.step is not ScreeningStep.BASIC_REPORT:
            return
        self._machine = SessionStateMachine()
        self._session_id = None
        self._lifecycle_status = LifecycleStatus.DRAFT
        self._validity = SessionValidity.UNKNOWN
        self._upload_status = UploadStatus.LOCAL_ONLY
        self._analysis_status = AnalysisStatus.NOT_REQUESTED
        self._report_status = ReportStatus.NOT_AVAILABLE
        self._report_id = None
        self._report_version = None
        self._error = None
        self._notice = None
        self.start_new_screening()

    def complete_acquisition(self) -> None:
        if self._machine.step is not ScreeningStep.ACQUIRING or self._session_id is None:
            return
        session_id = self._session_id
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
