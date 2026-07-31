from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import time
from typing import Protocol

from PySide6.QtCore import QTimer

from client.device.session_ui import HardwareUiFailure
from client.workflow.consent import (
    ConsentPolicy,
    ConsentReceipt,
    ConsentResolutionStatus,
    ConsentWorkflow,
    RequiredConsentDeclined,
)
from client.workflow.models import ClientError, WorkflowState
from client.workflow.state_machine import ScreeningStep
from client.local_analysis.display import DisplayRefreshController
from client.workflow.participant import (
    AnalysisProfile,
    ExternalIdType,
    FieldState,
    OptionalField,
    ParticipantWorkflow,
    SubjectResolutionStatus,
)

from .pages import PageId
from .engineering_maintenance import EngineeringMaintenanceService
from .session_deletion import CompletedSessionDeletionService
from .hardware_failure import resolve_hardware_ui_failure
from .live_display import LiveDisplayProjection
from .qt_shell import ScreeningWindow
from .ui_models import UiReadModelPort


class _CoordinatorPort(Protocol):
    @property
    def state(self) -> WorkflowState: ...

    def start_new_screening(self) -> None: ...

    def confirm_subject(self) -> None: ...

    def bind_participant(self, *, subject_uuid: str, consent_record_id: str) -> None: ...

    def complete_profile(self) -> None: ...

    def confirm_consent(self) -> None: ...

    def run_preflight(self) -> bool: ...

    def enter_position_guidance(self) -> bool: ...

    def start_acquisition(self) -> bool: ...

    def stop_acquisition(self) -> bool: ...

    def retry_screening(self) -> None: ...

    def export_current_report(self, destination: Path) -> None: ...

    def print_current_report(self) -> None: ...

    def complete_acquisition(self) -> None: ...

    def handle_device_disconnect(self, *, technical_detail: str) -> None: ...

    def handle_hardware_failure(self, *, error: ClientError) -> None: ...

    def observe_position(
        self,
        *,
        now_seconds: float,
        contact_ready: bool,
        in_valid_area: bool,
    ): ...

    def observe_acquisition_elapsed(self, *, elapsed_seconds: int) -> int | None: ...

    def start_next_screening(self) -> None: ...


class _DeviceSupportPort(Protocol):
    """Optional adapter boundary for privileged support operations."""

    def recheck_system(self) -> None: ...

    def export_diagnostic_bundle(self) -> None: ...


class ApplicationController:
    def __init__(
        self,
        coordinator: _CoordinatorPort,
        *,
        export_destination: Callable[[], Path | None] | None = None,
        participant: ParticipantWorkflow | None = None,
        consent: ConsentWorkflow | None = None,
        consent_policy: ConsentPolicy | None = None,
        display_refresh: DisplayRefreshController | None = None,
        live_display: LiveDisplayProjection | None = None,
        read_models: UiReadModelPort | None = None,
        device_support: _DeviceSupportPort | None = None,
        engineering_maintenance: EngineeringMaintenanceService | None = None,
        session_deletion: CompletedSessionDeletionService | None = None,
    ) -> None:
        self._coordinator = coordinator
        self._export_destination = export_destination or (lambda: None)
        self._participant = participant
        self._consent = consent
        self._consent_policy = consent_policy
        self._display_refresh = display_refresh
        self._live_display = live_display
        self._read_models = read_models
        self._device_support = device_support
        self._engineering_maintenance = engineering_maintenance
        self._session_deletion = session_deletion
        onboarding_dependencies = (participant, consent, consent_policy)
        if any(value is not None for value in onboarding_dependencies) and any(
            value is None for value in onboarding_dependencies
        ):
            raise ValueError(
                "participant, consent, and consent_policy must be configured together"
            )
        self.window = ScreeningWindow(on_action=self.dispatch)
        self.window.set_engineering_maintenance_available(
            engineering_maintenance is not None
        )
        self.window.set_session_deletion_available(session_deletion is not None)
        self._live_display_timer = QTimer(self.window)
        self._live_display_timer.setInterval(16)
        self._live_display_timer.timeout.connect(self._on_live_display_timer)
        self.refresh()

    def dispatch(self, action: str) -> None:
        if self._participant is not None and action in {
            "LOOKUP_SUBJECT",
            "CONFIRM_SUBJECT",
            "CREATE_ANONYMOUS_SUBJECT",
            "SAVE_PROFILE",
            "SKIP_PROFILE",
            "CONFIRM_CONSENT",
        }:
            self._dispatch_onboarding(action)
            return
        if action in {"VIEW_BASIC_REPORT", "VIEW_SELECTED_REPORT"}:
            self.window.show_page(PageId.REPORT_PREVIEW)
            return
        if action == "EXPORT_PDF":
            destination = self._export_destination()
            if destination is not None:
                state = self._coordinator.state
                if (
                    self._participant is not None
                    and state.report_id is not None
                    and state.report_version is not None
                ):
                    self._participant.record_selected_export(
                        report_id=state.report_id,
                        report_version=state.report_version,
                    )
                self._coordinator.export_current_report(destination)
            return
        if action == "PRINT_REPORT":
            self._coordinator.print_current_report()
            return
        if action in {"RECHECK_SYSTEM", "EXPORT_DIAGNOSTIC"}:
            self._dispatch_device_support(action)
            return
        if action == "OPEN_ENGINEERING_MAINTENANCE":
            if self._engineering_maintenance is None:
                self.window.show_form_error("工程检修功能尚未接入当前运行环境")
            else:
                self.window.show_engineering_maintenance(self._engineering_maintenance)
            return
        if action == "OPEN_SESSION_DELETION":
            if self._session_deletion is None:
                self.window.show_form_error("本地会话清理功能尚未接入当前运行环境")
            else:
                self.window.show_session_deletion(self._session_deletion)
            return
        if action == "CONFIRM_CONSENT":
            self._coordinator.confirm_consent()
            self.refresh()
            QTimer.singleShot(0, self._run_preflight)
            return
        if action == "RETRY_SCREENING":
            self._coordinator.retry_screening()
            self.refresh()
            QTimer.singleShot(0, self._run_preflight)
            return
        handlers: dict[str, Callable[[], object]] = {
            "START_NEW_SCREENING": self._start_new_screening,
            "CONFIRM_SUBJECT": self._coordinator.confirm_subject,
            "SAVE_PROFILE": self._coordinator.complete_profile,
            "SKIP_PROFILE": self._coordinator.complete_profile,
            "RECHECK": self._coordinator.run_preflight,
            "ENTER_POSITION": self._coordinator.enter_position_guidance,
            "START_ACQUISITION": self._coordinator.start_acquisition,
            "STOP_SCREENING": self._coordinator.stop_acquisition,
            "START_NEXT_SCREENING": self._start_next_screening,
        }
        try:
            handler = handlers[action]
        except KeyError as exc:
            raise KeyError(f"unsupported application action: {action}") from exc
        handler()
        self.refresh()

    def refresh(self) -> None:
        self.window.present_state(self._coordinator.state)
        self._sync_live_display_timer()
        if self._read_models is None:
            return
        self.window.present_dashboard(self._read_models.dashboard_snapshot())
        self.window.present_records(self._read_models.recent_records())
        self.window.present_support(self._read_models.support_snapshot())

    def on_acquisition_completed(self) -> None:
        self._coordinator.complete_acquisition()
        self.refresh()

    def on_device_disconnected(self, technical_detail: str) -> None:
        self._coordinator.handle_device_disconnect(technical_detail=technical_detail)
        self.refresh()

    def on_hardware_failure(self, failure: HardwareUiFailure) -> None:
        self._coordinator.handle_hardware_failure(
            error=resolve_hardware_ui_failure(failure)
        )
        self.refresh()

    def on_position_observation(
        self,
        *,
        now_seconds: float,
        contact_ready: bool,
        in_valid_area: bool,
    ) -> None:
        self._coordinator.observe_position(
            now_seconds=now_seconds,
            contact_ready=contact_ready,
            in_valid_area=in_valid_area,
        )
        self.refresh()

    def on_acquisition_elapsed(self, elapsed_seconds: int) -> None:
        self._coordinator.observe_acquisition_elapsed(
            elapsed_seconds=elapsed_seconds,
        )
        self.refresh()

    def on_display_tick(self, now_monotonic_seconds: float) -> bool:
        if self._display_refresh is None:
            return False
        frame = self._display_refresh.poll(
            now_monotonic_seconds=now_monotonic_seconds
        )
        if frame is None:
            return False
        self.window.present_display_frame(frame)
        return True

    def _sync_live_display_timer(self) -> None:
        should_run = (
            self._live_display is not None
            and self._display_refresh is not None
            and self._coordinator.state.step is ScreeningStep.ACQUIRING
        )
        if should_run and not self._live_display_timer.isActive():
            self._live_display_timer.start()
        elif not should_run and self._live_display_timer.isActive():
            self._live_display_timer.stop()

    def _on_live_display_timer(self) -> None:
        """Run entirely in the Qt thread; hardware reads stay behind its port."""
        if self._live_display is None:
            return
        self._live_display.poll()
        self.on_display_tick(time.monotonic())

    def _run_preflight(self) -> None:
        self._coordinator.run_preflight()
        self.refresh()

    def _start_new_screening(self) -> None:
        if self._participant is not None:
            self._participant.reset()
            self._consent.reset()
        self._coordinator.start_new_screening()

    def _start_next_screening(self) -> None:
        if self._participant is not None:
            self._participant.reset()
            self._consent.reset()
        self._coordinator.start_next_screening()

    def _dispatch_device_support(self, action: str) -> None:
        if self._device_support is None:
            self.window.show_form_error("设备支持功能尚未接入当前运行环境")
            return
        if action == "RECHECK_SYSTEM":
            self._device_support.recheck_system()
        else:
            self._device_support.export_diagnostic_bundle()

    def _dispatch_onboarding(self, action: str) -> None:
        try:
            if action == "LOOKUP_SUBJECT":
                self._lookup_subject()
                return
            if action == "CONFIRM_SUBJECT":
                self._confirm_selected_subject()
                return
            if action == "CREATE_ANONYMOUS_SUBJECT":
                self._participant.create_anonymous()
                self._coordinator.confirm_subject()
                self.refresh()
                return
            if action in {"SAVE_PROFILE", "SKIP_PROFILE"}:
                self._complete_profile(save=action == "SAVE_PROFILE")
                return
            if action == "CONFIRM_CONSENT":
                necessary, research = self.window.consent_choices()
                receipt = self._consent.confirm(
                    necessary_accepted=necessary,
                    research_accepted=research,
                )
                self._accept_consent(receipt)
                return
        except (ValueError, RuntimeError) as exc:
            message = (
                "请勾选必要处理授权后再继续"
                if isinstance(exc, RequiredConsentDeclined)
                else str(exc)
            )
            self.window.show_form_error(message)

    def _lookup_subject(self) -> None:
        id_type, external_id = self.window.subject_identifier()
        if not external_id.strip():
            raise ValueError("请输入机构编号")
        resolution = self._participant.resolve_external_id(
            ExternalIdType(id_type),
            external_id,
        )
        summaries = {
            SubjectResolutionStatus.FOUND: "已找到唯一档案，请确认后继续",
            SubjectResolutionStatus.NOT_FOUND: "未找到档案；确认后将按此机构编号建档",
            SubjectResolutionStatus.CONFLICT: "找到多个可能档案，无法自动选择，请核对编号",
        }
        if resolution.status is SubjectResolutionStatus.CONFLICT:
            self.window.show_subject_conflict()
        else:
            self.window.set_subject_match_summary(summaries[resolution.status])

    def _confirm_selected_subject(self) -> None:
        participant_state = self._participant.state
        if participant_state.selected_subject is None:
            if participant_state.resolution_status is SubjectResolutionStatus.NOT_FOUND:
                self._participant.create_from_last_lookup(AnalysisProfile.unknown())
            elif participant_state.resolution_status is SubjectResolutionStatus.CONFLICT:
                raise RuntimeError("找到多个档案，不能自动合并或继续")
            else:
                raise RuntimeError("请先查找机构编号或选择快速建档")
        self._coordinator.confirm_subject()
        self.refresh()

    def _complete_profile(self, *, save: bool) -> None:
        subject = self._participant.state.selected_subject
        if subject is None:
            raise RuntimeError("请先确认受试者")
        if save:
            self._participant.update_selected_profile(self._profile_from_form())
        self._coordinator.complete_profile()
        resolution = self._consent.resolve(subject.subject_uuid, self._consent_policy)
        if resolution.status is ConsentResolutionStatus.REUSED:
            self._accept_consent(resolution.receipt)
            return
        self.refresh()

    def _profile_from_form(self) -> AnalysisProfile:
        form = self.window.profile_form_values()
        return AnalysisProfile(
            age_band=self._optional_text(*form["ageBand"], label="年龄段"),
            sex=self._optional_text(*form["sex"], label="性别"),
            height_cm=self._optional_number(*form["height"], label="身高"),
            weight_kg=self._optional_number(*form["weight"], label="体重"),
            condition_tags=self._optional_tags(*form["conditionTags"]),
            injury_tags=self._optional_tags(*form["injuryTags"]),
        )

    @staticmethod
    def _optional_text(
        state_value: str,
        value: str,
        *,
        label: str,
    ) -> OptionalField[str]:
        state = FieldState(state_value)
        if state is not FieldState.PROVIDED:
            return OptionalField(state)
        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{label}标记为已填写时必须选择或输入内容")
        return OptionalField(state, normalized)

    @staticmethod
    def _optional_number(
        state_value: str,
        value: str,
        *,
        label: str,
    ) -> OptionalField[float]:
        state = FieldState(state_value)
        if state is not FieldState.PROVIDED:
            return OptionalField(state)
        try:
            number = float(value.strip())
        except ValueError as exc:
            raise ValueError(f"{label}需填写有效数字") from exc
        if number <= 0:
            raise ValueError(f"{label}必须大于 0")
        return OptionalField(state, number)

    @staticmethod
    def _optional_tags(
        state_value: str,
        value: str,
    ) -> OptionalField[tuple[str, ...]]:
        state = FieldState(state_value)
        if state is not FieldState.PROVIDED:
            return OptionalField(state)
        tags = tuple(
            item.strip()
            for item in value.replace("，", ",").split(",")
            if item.strip()
        )
        if not tags:
            raise ValueError("标签标记为已填写时必须输入内容")
        return OptionalField(state, tags)

    def _accept_consent(self, receipt: ConsentReceipt | None) -> None:
        if receipt is None:
            raise RuntimeError("未获得有效授权记录")
        subject = self._participant.state.selected_subject
        if subject is None or receipt.subject_uuid != subject.subject_uuid:
            raise RuntimeError("授权记录与当前受试者不一致")
        self._coordinator.bind_participant(
            subject_uuid=subject.subject_uuid,
            consent_record_id=receipt.consent_record_id,
        )
        self._coordinator.confirm_consent()
        self.refresh()
        QTimer.singleShot(0, self._run_preflight)
