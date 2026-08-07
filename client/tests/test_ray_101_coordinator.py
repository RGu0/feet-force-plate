from __future__ import annotations

import unittest
from pathlib import Path

from client.workflow.coordinator import ScreeningCoordinator
from client.workflow.models import (
    ClientAction,
    ClientError,
    AnalysisStatus,
    LifecycleStatus,
    PreflightCheck,
    PreflightSummary,
    QualityOutcome,
    QualityResult,
    ReportStatus,
    ScreeningParticipantContext,
    SessionValidity,
    UploadStatus,
)
from client.workflow.state_machine import ScreeningStep
from client.workflow.protocol import ProtocolSnapshot


class _PreflightPort:
    def __init__(self, summary: PreflightSummary) -> None:
        self.summary = summary

    def run_preflight(self) -> PreflightSummary:
        return self.summary


class _SessionPort:
    def __init__(self, *, create_error: Exception | None = None) -> None:
        self.create_calls = 0
        self.contexts: list[ScreeningParticipantContext] = []
        self.incomplete: list[str] = []
        self.finalized: list[str] = []
        self.create_error = create_error

    def create_session(
        self,
        context: ScreeningParticipantContext,
        protocol: ProtocolSnapshot,
    ) -> str:
        self.create_calls += 1
        self.contexts.append(context)
        _ = protocol
        if self.create_error is not None:
            raise self.create_error
        return f"session-{self.create_calls}"

    def mark_incomplete(self, session_id: str) -> None:
        self.incomplete.append(session_id)

    def finalize(self, session_id: str) -> None:
        self.finalized.append(session_id)


class _AcquisitionPort:
    def __init__(self, *, start_error: Exception | None = None) -> None:
        self.started: list[str] = []
        self.stopped: list[str] = []
        self.start_error = start_error

    def start(self, session_id: str) -> None:
        if self.start_error is not None:
            raise self.start_error
        self.started.append(session_id)

    def stop(self, session_id: str) -> None:
        self.stopped.append(session_id)


class _AnalysisPort:
    def __init__(
        self,
        result: QualityResult,
        *,
        analyze_error: Exception | None = None,
    ) -> None:
        self.result = result
        self.analyze_error = analyze_error
        self.analyzed: list[str] = []

    def analyze(self, session_id: str) -> QualityResult:
        self.analyzed.append(session_id)
        if self.analyze_error is not None:
            raise self.analyze_error
        return self.result


class _ReportPort:
    def __init__(self, *, create_error: Exception | None = None) -> None:
        self.created: list[str] = []
        self.exports: list[tuple[str, int, Path]] = []
        self.prints: list[tuple[str, int]] = []
        self.create_error = create_error

    def create_basic_report(self, session_id: str) -> tuple[str, int]:
        if self.create_error is not None:
            raise self.create_error
        self.created.append(session_id)
        return ("report-1", 1)

    def export_pdf(self, report_id: str, version: int, destination: Path) -> None:
        self.exports.append((report_id, version, destination))

    def print_report(self, report_id: str, version: int) -> None:
        self.prints.append((report_id, version))


class _TelemetryPort:
    def __init__(self) -> None:
        self.errors: list[tuple[str, str | None, str]] = []

    def record_error(
        self,
        *,
        code: str,
        session_id: str | None,
        technical_detail: str,
    ) -> None:
        self.errors.append((code, session_id, technical_detail))


def _coordinator(
    *,
    preflight: _PreflightPort,
    sessions: _SessionPort,
    acquisition: _AcquisitionPort | None = None,
    analysis: _AnalysisPort | None = None,
    reports: _ReportPort | None = None,
    telemetry: _TelemetryPort | None = None,
) -> ScreeningCoordinator:
    coordinator = ScreeningCoordinator(
        preflight=preflight,
        sessions=sessions,
        acquisition=acquisition or _AcquisitionPort(),
        analysis=analysis
        or _AnalysisPort(QualityResult(outcome=QualityOutcome.VALID)),
        reports=reports or _ReportPort(),
        telemetry=telemetry or _TelemetryPort(),
    )
    coordinator.bind_participant(
        subject_uuid="subject-test",
        consent_record_id="consent-test",
    )
    return coordinator


def _start_acquisition(coordinator: ScreeningCoordinator) -> bool:
    if coordinator.state.step is ScreeningStep.PREFLIGHT:
        assert coordinator.enter_position_guidance()
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
    return coordinator.start_acquisition()


class CoordinatorPreflightTests(unittest.TestCase):
    def test_failed_preflight_stays_repairable_without_creating_session(self) -> None:
        preflight = _PreflightPort(
            PreflightSummary(
                checks=(
                    PreflightCheck(
                        key="device",
                        ready=False,
                        error_code="E-DEV-001",
                        operator_message="未检测到压力设备，请检查连接",
                    ),
                )
            )
        )
        sessions = _SessionPort()
        coordinator = _coordinator(preflight=preflight, sessions=sessions)
        coordinator.start_new_screening()
        coordinator.confirm_subject()
        coordinator.complete_profile()
        coordinator.confirm_consent()

        ready = coordinator.run_preflight()

        self.assertFalse(ready)
        self.assertEqual(coordinator.state.step, ScreeningStep.PREFLIGHT)
        self.assertEqual(sessions.create_calls, 0)
        self.assertEqual(coordinator.state.error.code, "E-DEV-001")
        self.assertEqual(
            coordinator.state.error.operator_message,
            "未检测到压力设备，请检查连接",
        )
        self.assertEqual(coordinator.state.error.action, ClientAction.RECHECK)

    def test_successful_preflight_waits_for_explicit_operator_entry(self) -> None:
        check = PreflightCheck(key="device", ready=True, operator_message="已连接")
        coordinator = _coordinator(
            preflight=_PreflightPort(PreflightSummary(checks=(check,))),
            sessions=_SessionPort(),
        )
        coordinator.start_new_screening()
        coordinator.confirm_subject()
        coordinator.complete_profile()
        coordinator.confirm_consent()

        self.assertTrue(coordinator.run_preflight())
        self.assertEqual(coordinator.state.step, ScreeningStep.PREFLIGHT)
        self.assertTrue(coordinator.state.preflight_ready)
        self.assertEqual(coordinator.state.preflight_checks, (check,))

        self.assertTrue(coordinator.enter_position_guidance())
        self.assertEqual(coordinator.state.step, ScreeningStep.POSITION_GUIDANCE)

    def test_start_is_guarded_against_duplicate_session_creation(self) -> None:
        preflight = _PreflightPort(
            PreflightSummary(checks=(PreflightCheck(key="device", ready=True),))
        )
        sessions = _SessionPort()
        acquisition = _AcquisitionPort()
        coordinator = _coordinator(
            preflight=preflight,
            sessions=sessions,
            acquisition=acquisition,
        )
        coordinator.start_new_screening()
        coordinator.confirm_subject()
        coordinator.complete_profile()
        coordinator.confirm_consent()
        self.assertTrue(coordinator.run_preflight())

        first_start = _start_acquisition(coordinator)
        duplicate_start = _start_acquisition(coordinator)

        self.assertTrue(first_start)
        self.assertFalse(duplicate_start)
        self.assertEqual(coordinator.state.step, ScreeningStep.ACQUIRING)
        self.assertEqual(coordinator.state.session_id, "session-1")
        self.assertEqual(sessions.create_calls, 1)
        self.assertEqual(acquisition.started, ["session-1"])

    def test_acquisition_start_failure_closes_created_session_with_safe_error(self) -> None:
        preflight = _PreflightPort(
            PreflightSummary(checks=(PreflightCheck(key="device", ready=True),))
        )
        sessions = _SessionPort()
        acquisition = _AcquisitionPort(start_error=RuntimeError("driver stack"))
        telemetry = _TelemetryPort()
        coordinator = _coordinator(
            preflight=preflight,
            sessions=sessions,
            acquisition=acquisition,
            telemetry=telemetry,
        )
        coordinator.start_new_screening()
        coordinator.confirm_subject()
        coordinator.complete_profile()
        coordinator.confirm_consent()
        coordinator.run_preflight()

        started = _start_acquisition(coordinator)

        self.assertFalse(started)
        self.assertEqual(coordinator.state.step, ScreeningStep.INCOMPLETE)
        self.assertEqual(coordinator.state.validity, SessionValidity.INCOMPLETE)
        self.assertEqual(sessions.incomplete, ["session-1"])
        self.assertEqual(coordinator.state.error.code, "E-ACQ-001")
        self.assertNotIn("driver stack", repr(coordinator.state))
        self.assertEqual(
            telemetry.errors,
            [("E-ACQ-001", "session-1", "RuntimeError: driver stack")],
        )

    def test_session_creation_failure_stays_before_acquisition_with_safe_error(self) -> None:
        preflight = _PreflightPort(
            PreflightSummary(checks=(PreflightCheck(key="device", ready=True),))
        )
        sessions = _SessionPort(create_error=OSError("database locked"))
        telemetry = _TelemetryPort()
        coordinator = _coordinator(
            preflight=preflight,
            sessions=sessions,
            telemetry=telemetry,
        )
        coordinator.start_new_screening()
        coordinator.confirm_subject()
        coordinator.complete_profile()
        coordinator.confirm_consent()
        coordinator.run_preflight()

        started = _start_acquisition(coordinator)

        self.assertFalse(started)
        self.assertEqual(coordinator.state.step, ScreeningStep.POSITION_GUIDANCE)
        self.assertIsNone(coordinator.state.session_id)
        self.assertEqual(coordinator.state.validity, SessionValidity.UNKNOWN)
        self.assertEqual(coordinator.state.error.code, "E-DAT-001")
        self.assertNotIn("database locked", repr(coordinator.state))
        self.assertEqual(
            telemetry.errors,
            [("E-DAT-001", None, "OSError: database locked")],
        )

    def test_disconnect_uses_safe_error_and_marks_session_incomplete(self) -> None:
        preflight = _PreflightPort(
            PreflightSummary(checks=(PreflightCheck(key="device", ready=True),))
        )
        sessions = _SessionPort()
        telemetry = _TelemetryPort()
        coordinator = _coordinator(
            preflight=preflight,
            sessions=sessions,
            telemetry=telemetry,
        )
        coordinator.start_new_screening()
        coordinator.confirm_subject()
        coordinator.complete_profile()
        coordinator.confirm_consent()
        coordinator.run_preflight()
        _start_acquisition(coordinator)

        coordinator.handle_device_disconnect(
            technical_detail="SerialException: /dev/cu.usbserial stack trace"
        )

        self.assertEqual(coordinator.state.step, ScreeningStep.INCOMPLETE)
        self.assertEqual(coordinator.state.validity, SessionValidity.INCOMPLETE)
        self.assertEqual(sessions.incomplete, ["session-1"])
        self.assertEqual(coordinator.state.error.code, "E-DEV-002")
        self.assertEqual(
            coordinator.state.error.operator_message,
            "压力设备连接已中断，本次检测未完成",
        )
        self.assertEqual(coordinator.state.error.action, ClientAction.RETRY_SCREENING)
        self.assertNotIn("SerialException", repr(coordinator.state))
        self.assertNotIn("usbserial", repr(coordinator.state))
        self.assertEqual(
            telemetry.errors,
            [
                (
                    "E-DEV-002",
                    "session-1",
                    "SerialException: /dev/cu.usbserial stack trace",
                )
            ],
        )

    def test_typed_hardware_failure_closes_capture_with_stable_audit_only(self) -> None:
        preflight = _PreflightPort(
            PreflightSummary(checks=(PreflightCheck(key="device", ready=True),))
        )
        sessions = _SessionPort()
        telemetry = _TelemetryPort()
        reports = _ReportPort()
        coordinator = _coordinator(
            preflight=preflight,
            sessions=sessions,
            telemetry=telemetry,
            reports=reports,
        )
        coordinator.start_new_screening()
        coordinator.confirm_subject()
        coordinator.complete_profile()
        coordinator.confirm_consent()
        coordinator.run_preflight()
        assert _start_acquisition(coordinator)

        coordinator.handle_hardware_failure(
            error=ClientError(
                code="E-DAT-102",
                operator_message="本次检测未能完成本地保存，请联系技术支持。",
                action=ClientAction.CONTACT_SUPPORT,
            )
        )

        self.assertEqual(coordinator.state.step, ScreeningStep.INCOMPLETE)
        self.assertEqual(coordinator.state.validity, SessionValidity.INCOMPLETE)
        self.assertEqual(sessions.incomplete, ["session-1"])
        self.assertEqual(coordinator.state.error.action, ClientAction.CONTACT_SUPPORT)
        self.assertEqual(reports.created, [])
        self.assertEqual(
            telemetry.errors,
            [("E-DAT-102", "session-1", "hardware_ui_failure:E-DAT-102")],
        )

    def test_quality_failure_requires_retry_and_never_creates_report(self) -> None:
        preflight = _PreflightPort(
            PreflightSummary(checks=(PreflightCheck(key="device", ready=True),))
        )
        sessions = _SessionPort()
        analysis = _AnalysisPort(QualityResult(outcome=QualityOutcome.INVALID))
        reports = _ReportPort()
        coordinator = _coordinator(
            preflight=preflight,
            sessions=sessions,
            analysis=analysis,
            reports=reports,
        )
        coordinator.start_new_screening()
        coordinator.confirm_subject()
        coordinator.complete_profile()
        coordinator.confirm_consent()
        coordinator.run_preflight()
        _start_acquisition(coordinator)

        coordinator.complete_acquisition()

        self.assertEqual(coordinator.state.step, ScreeningStep.RETRY_REQUIRED)
        self.assertEqual(coordinator.state.validity, SessionValidity.INVALID)
        self.assertEqual(sessions.finalized, ["session-1"])
        self.assertEqual(analysis.analyzed, ["session-1"])
        self.assertEqual(reports.created, [])
        self.assertEqual(coordinator.state.error.action, ClientAction.RETRY_SCREENING)

    def test_valid_session_exposes_versioned_basic_report(self) -> None:
        preflight = _PreflightPort(
            PreflightSummary(checks=(PreflightCheck(key="device", ready=True),))
        )
        sessions = _SessionPort()
        analysis = _AnalysisPort(QualityResult(outcome=QualityOutcome.VALID))
        reports = _ReportPort()
        coordinator = _coordinator(
            preflight=preflight,
            sessions=sessions,
            analysis=analysis,
            reports=reports,
        )
        coordinator.start_new_screening()
        coordinator.confirm_subject()
        coordinator.complete_profile()
        coordinator.confirm_consent()
        coordinator.run_preflight()
        _start_acquisition(coordinator)

        coordinator.complete_acquisition()

        self.assertEqual(coordinator.state.step, ScreeningStep.BASIC_REPORT)
        self.assertEqual(coordinator.state.validity, SessionValidity.VALID)
        self.assertEqual(coordinator.state.report_status, ReportStatus.BASIC_READY)
        self.assertEqual(coordinator.state.report_id, "report-1")
        self.assertEqual(coordinator.state.report_version, 1)
        self.assertEqual(reports.created, ["session-1"])

    def test_report_generation_failure_is_visible_without_exposing_stack(self) -> None:
        preflight = _PreflightPort(
            PreflightSummary(checks=(PreflightCheck(key="device", ready=True),))
        )
        reports = _ReportPort(create_error=RuntimeError("template stack"))
        telemetry = _TelemetryPort()
        coordinator = _coordinator(
            preflight=preflight,
            sessions=_SessionPort(),
            reports=reports,
            telemetry=telemetry,
        )
        coordinator.start_new_screening()
        coordinator.confirm_subject()
        coordinator.complete_profile()
        coordinator.confirm_consent()
        coordinator.run_preflight()
        _start_acquisition(coordinator)

        coordinator.complete_acquisition()

        self.assertEqual(coordinator.state.step, ScreeningStep.FAILED)
        self.assertEqual(coordinator.state.validity, SessionValidity.VALID)
        self.assertEqual(coordinator.state.report_status, ReportStatus.NOT_AVAILABLE)
        self.assertEqual(coordinator.state.error.code, "E-RPT-001")
        self.assertEqual(coordinator.state.error.action, ClientAction.CONTACT_SUPPORT)
        self.assertNotIn("template stack", repr(coordinator.state))
        self.assertEqual(
            telemetry.errors,
            [("E-RPT-001", "session-1", "RuntimeError: template stack")],
        )

    def test_analysis_failure_is_visible_instead_of_leaving_finalizing_stuck(
        self,
    ) -> None:
        preflight = _PreflightPort(
            PreflightSummary(checks=(PreflightCheck(key="device", ready=True),))
        )
        analysis = _AnalysisPort(
            QualityResult(outcome=QualityOutcome.VALID),
            analyze_error=RuntimeError("analysis stack"),
        )
        telemetry = _TelemetryPort()
        coordinator = _coordinator(
            preflight=preflight,
            sessions=_SessionPort(),
            analysis=analysis,
            telemetry=telemetry,
        )
        coordinator.start_new_screening()
        coordinator.confirm_subject()
        coordinator.complete_profile()
        coordinator.confirm_consent()
        coordinator.run_preflight()
        _start_acquisition(coordinator)

        coordinator.complete_acquisition()

        self.assertEqual(coordinator.state.step, ScreeningStep.FAILED)
        self.assertEqual(coordinator.state.error.code, "E-RPT-001")
        self.assertEqual(coordinator.state.error.action, ClientAction.CONTACT_SUPPORT)
        self.assertNotIn("analysis stack", repr(coordinator.state))
        self.assertEqual(
            telemetry.errors,
            [("E-RPT-001", "session-1", "RuntimeError: analysis stack")],
        )

    def test_export_and_print_remain_pinned_to_the_viewed_report_version(self) -> None:
        preflight = _PreflightPort(
            PreflightSummary(checks=(PreflightCheck(key="device", ready=True),))
        )
        reports = _ReportPort()
        coordinator = _coordinator(
            preflight=preflight,
            sessions=_SessionPort(),
            reports=reports,
        )
        coordinator.start_new_screening()
        coordinator.confirm_subject()
        coordinator.complete_profile()
        coordinator.confirm_consent()
        coordinator.run_preflight()
        _start_acquisition(coordinator)
        coordinator.complete_acquisition()
        destination = Path("/tmp/masked-20260720-basic-v1.pdf")

        coordinator.export_current_report(destination)
        coordinator.print_current_report()

        self.assertEqual(reports.exports, [("report-1", 1, destination)])
        self.assertEqual(reports.prints, [("report-1", 1)])

    def test_sync_and_cloud_failure_do_not_invalidate_basic_report(self) -> None:
        preflight = _PreflightPort(
            PreflightSummary(checks=(PreflightCheck(key="device", ready=True),))
        )
        coordinator = _coordinator(
            preflight=preflight,
            sessions=_SessionPort(),
        )
        coordinator.start_new_screening()
        coordinator.confirm_subject()
        coordinator.complete_profile()
        coordinator.confirm_consent()
        coordinator.run_preflight()
        _start_acquisition(coordinator)
        coordinator.complete_acquisition()

        coordinator.record_upload_status(UploadStatus.PENDING)
        coordinator.record_cloud_failure()

        self.assertEqual(coordinator.state.validity, SessionValidity.VALID)
        self.assertEqual(coordinator.state.upload_status, UploadStatus.PENDING)
        self.assertEqual(coordinator.state.analysis_status, AnalysisStatus.FAILED)
        self.assertEqual(coordinator.state.report_status, ReportStatus.CLOUD_FAILED)
        self.assertEqual(coordinator.state.report_id, "report-1")
        self.assertEqual(coordinator.state.report_version, 1)
        self.assertEqual(
            coordinator.state.notice,
            "基础报告可继续使用，完整分析正在自动重试",
        )

    def test_lifecycle_status_is_separate_from_ui_and_report_status(self) -> None:
        preflight = _PreflightPort(
            PreflightSummary(checks=(PreflightCheck(key="device", ready=True),))
        )
        coordinator = _coordinator(
            preflight=preflight,
            sessions=_SessionPort(),
        )
        self.assertEqual(coordinator.state.lifecycle_status, LifecycleStatus.DRAFT)
        coordinator.start_new_screening()
        coordinator.confirm_subject()
        coordinator.complete_profile()
        coordinator.confirm_consent()
        self.assertEqual(coordinator.state.lifecycle_status, LifecycleStatus.PREFLIGHT)
        coordinator.run_preflight()
        _start_acquisition(coordinator)
        self.assertEqual(coordinator.state.lifecycle_status, LifecycleStatus.ACQUIRING)

        coordinator.complete_acquisition()

        self.assertEqual(coordinator.state.lifecycle_status, LifecycleStatus.CLOSED)
        self.assertEqual(coordinator.state.report_status, ReportStatus.BASIC_READY)

    def test_operator_stop_is_safe_and_idempotent(self) -> None:
        preflight = _PreflightPort(
            PreflightSummary(checks=(PreflightCheck(key="device", ready=True),))
        )
        sessions = _SessionPort()
        acquisition = _AcquisitionPort()
        reports = _ReportPort()
        coordinator = _coordinator(
            preflight=preflight,
            sessions=sessions,
            acquisition=acquisition,
            reports=reports,
        )
        coordinator.start_new_screening()
        coordinator.confirm_subject()
        coordinator.complete_profile()
        coordinator.confirm_consent()
        coordinator.run_preflight()
        _start_acquisition(coordinator)

        first_stop = coordinator.stop_acquisition()
        duplicate_stop = coordinator.stop_acquisition()

        self.assertTrue(first_stop)
        self.assertFalse(duplicate_stop)
        self.assertEqual(acquisition.stopped, ["session-1"])
        self.assertEqual(sessions.incomplete, ["session-1"])
        self.assertEqual(coordinator.state.step, ScreeningStep.INCOMPLETE)
        self.assertEqual(coordinator.state.validity, SessionValidity.INCOMPLETE)
        self.assertEqual(reports.created, [])
        self.assertEqual(coordinator.state.error.code, "E-ACQ-003")
        self.assertEqual(coordinator.state.error.action, ClientAction.RETRY_SCREENING)

    def test_retry_creates_a_new_session_instead_of_resuming_incomplete_data(self) -> None:
        preflight = _PreflightPort(
            PreflightSummary(checks=(PreflightCheck(key="device", ready=True),))
        )
        sessions = _SessionPort()
        acquisition = _AcquisitionPort()
        coordinator = _coordinator(
            preflight=preflight,
            sessions=sessions,
            acquisition=acquisition,
        )
        coordinator.start_new_screening()
        coordinator.confirm_subject()
        coordinator.complete_profile()
        coordinator.confirm_consent()
        coordinator.run_preflight()
        _start_acquisition(coordinator)
        coordinator.stop_acquisition()

        coordinator.retry_screening()
        self.assertEqual(coordinator.state.step, ScreeningStep.PREFLIGHT)
        self.assertFalse(coordinator.state.preflight_ready)
        self.assertTrue(coordinator.run_preflight())
        second_start = _start_acquisition(coordinator)

        self.assertTrue(second_start)
        self.assertEqual(coordinator.state.step, ScreeningStep.ACQUIRING)
        self.assertEqual(coordinator.state.session_id, "session-2")
        self.assertEqual(acquisition.started, ["session-1", "session-2"])
        self.assertEqual(sessions.create_calls, 2)

    def test_start_next_screening_clears_transient_state_and_keeps_records_external(self) -> None:
        preflight = _PreflightPort(
            PreflightSummary(checks=(PreflightCheck(key="device", ready=True),))
        )
        coordinator = _coordinator(
            preflight=preflight,
            sessions=_SessionPort(),
        )
        coordinator.start_new_screening()
        coordinator.confirm_subject()
        coordinator.complete_profile()
        coordinator.confirm_consent()
        coordinator.run_preflight()
        _start_acquisition(coordinator)
        coordinator.complete_acquisition()

        coordinator.start_next_screening()

        self.assertEqual(
            coordinator.state.step,
            ScreeningStep.SUBJECT_IDENTIFICATION,
        )
        self.assertIsNone(coordinator.state.session_id)
        self.assertEqual(coordinator.state.validity, SessionValidity.UNKNOWN)
        self.assertEqual(coordinator.state.report_status, ReportStatus.NOT_AVAILABLE)
        self.assertIsNone(coordinator.state.report_id)
        self.assertIsNone(coordinator.state.report_version)


if __name__ == "__main__":
    unittest.main()
