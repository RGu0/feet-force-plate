from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QTimer, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtSvgWidgets import QSvgWidget
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from client.local_analysis.display import DisplayFrame
from client.reporting.copy import report_badges, report_parameter_note
from client.reporting.models import BasicReportDocument
from client.hardware_standardization.dynamic_defect_mask import DynamicDefectStatus
from client.workflow.models import ClientAction, ReportStatus, SessionValidity, WorkflowState

from .design_system import apply_design_system
from .app_icon import application_icon
from .heatmap import PhysicalGridOverlay
from .engineering_maintenance import (
    EngineeringMaintenanceAccessDenied,
    EngineeringMaintenanceConnectionUnavailable,
    EngineeringMaintenanceDeviceUnbound,
    EngineeringMaintenanceService,
    EngineeringMaintenanceSnapshot,
)
from .session_deletion import (
    CompletedSessionDeletionService,
    SessionDeletionConfirmationRequired,
)
from .session_lock import (
    LockState,
    SessionActivity,
    SessionLockController,
)
from .heatmap import HeatmapWidget
from .pages import PAGE_DEFINITIONS, PageId, page_for_step
from .position_guide import StageGuidanceWidget
from .ui_models import DashboardSnapshot, ScreeningRecordRow, SupportSnapshot


_ACTION_LABELS = {
    "START_NEW_SCREENING": "开始新的检测",
    "CONFIRM_SUBJECT": "确认并继续",
    "CREATE_ANONYMOUS_SUBJECT": "无机构编号，快速建档",
    "SAVE_PROFILE": "保存并继续",
    "SKIP_PROFILE": "跳过",
    "CONFIRM_CONSENT": "同意并继续",
    "RECHECK": "重新检查",
    "START_ACQUISITION": "开始本段",
    "STOP_SCREENING": "停止检测",
    "VIEW_BASIC_REPORT": "查看基础报告",
    "START_NEXT_SCREENING": "开始下一位检测",
    "RETRY_SCREENING": "重新检测",
    "VIEW_SELECTED_REPORT": "查看报告",
    "EXPORT_PDF": "导出 PDF",
    "PRINT_REPORT": "打印",
    "RECHECK_SYSTEM": "重新检查",
    "EXPORT_DIAGNOSTIC": "导出问题诊断包",
    "OPEN_ENGINEERING_MAINTENANCE": "工程检修",
    "OPEN_SESSION_DELETION": "本地会话清理",
}

_WIZARD_STEPS = ("受试者", "选填信息", "授权确认", "设备预检", "站位引导")
_TOPBAR_PAGES = {PageId.WORKBENCH, PageId.RESULT, PageId.RECORDS, PageId.SUPPORT}


class _DefectDistributionWidget(QWidget):
    """Render only saved defect-mask markers; never a live pressure frame."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("engineeringDefectDistribution")
        self.setAccessibleName("工程检修坏点分布图")
        self.setMinimumSize(420, 280)
        self._snapshot: EngineeringMaintenanceSnapshot | None = None

    def set_snapshot(self, snapshot: EngineeringMaintenanceSnapshot) -> None:
        self._snapshot = snapshot
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        rect = self.rect().adjusted(12, 12, -12, -12)
        painter.fillRect(rect, QColor("#F5F7FA"))
        painter.setPen(QPen(QColor("#A8B2C1"), 1))
        painter.drawRect(rect)
        snapshot = self._snapshot
        if snapshot is None:
            painter.setPen(QColor("#697386"))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "完成工程确认后显示已保存的坏点掩码")
            return
        rows, columns = snapshot.shape
        cell_width = rect.width() / columns
        cell_height = rect.height() / rows
        colors = {
            "SUSPECT": QColor("#E7A93A"),
            "REPAIRABLE": QColor("#D95652"),
        }
        for cell in snapshot.marked_cells:
            painter.fillRect(
                int(rect.left() + cell.column * cell_width),
                int(rect.top() + cell.row * cell_height),
                max(1, int(cell_width)),
                max(1, int(cell_height)),
                colors[cell.status.value],
            )


class _EngineeringMaintenanceDialog(QDialog):
    """One-time confirmation dialog for a deployed engineering service."""

    def __init__(self, service: EngineeringMaintenanceService, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("engineeringMaintenanceDialog")
        self.setWindowTitle("工程检修")
        self.setModal(True)
        self.setMinimumSize(620, 560)
        self._service = service
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(12)
        title = QLabel("工程检修 · 坏点分布")
        title.setObjectName("engineeringMaintenanceTitle")
        title.setStyleSheet("font-size: 22px; font-weight: 600;")
        layout.addWidget(title)
        instruction = QLabel(
            "仅限已授权工程人员。输入由部署层校验的确认信息后，读取当前已绑定设备的保存掩码。"
        )
        instruction.setWordWrap(True)
        layout.addWidget(instruction)
        selector = QComboBox()
        selector.setObjectName("engineeringMaintenanceDeviceSelector")
        selector.setAccessibleName("已绑定工程设备")
        self._refresh_device_selector(selector)
        layout.addWidget(selector)
        device_id = QLineEdit()
        device_id.setObjectName("engineeringMaintenanceDeviceId")
        device_id.setPlaceholderText("添加或重新绑定的设备资产编号")
        device_id.setAccessibleName("工程设备资产编号")
        layout.addWidget(device_id)
        confirmation = QLineEdit()
        confirmation.setObjectName("engineeringMaintenanceConfirmation")
        confirmation.setEchoMode(QLineEdit.EchoMode.Password)
        confirmation.setPlaceholderText("输入工程确认信息")
        confirmation.setAccessibleName("工程确认信息")
        layout.addWidget(confirmation)
        bind = QPushButton("确认并绑定当前连接设备")
        bind.setObjectName("BIND_ENGINEERING_DEVICE")
        bind.clicked.connect(self._bind_current_device)
        layout.addWidget(bind, alignment=Qt.AlignmentFlag.AlignLeft)
        confirm = QPushButton("确认并查看")
        confirm.setObjectName("CONFIRM_ENGINEERING_MAINTENANCE")
        confirm.clicked.connect(self._load_distribution)
        layout.addWidget(confirm, alignment=Qt.AlignmentFlag.AlignLeft)
        status = QLabel("尚未读取设备掩码")
        status.setObjectName("engineeringMaintenanceStatus")
        status.setWordWrap(True)
        layout.addWidget(status)
        distribution = _DefectDistributionWidget()
        layout.addWidget(distribution, 1)
        summary = QLabel("黄色 SUSPECT 0 · 红色 REPAIRABLE 0")
        summary.setObjectName("engineeringMaintenanceSummary")
        layout.addWidget(summary)
        boundary = QLabel(
            "只读：不展示原始压力、帧证据、会话或协议数据；此处不能修改或清除坏点掩码。"
        )
        boundary.setObjectName("engineeringMaintenanceBoundary")
        boundary.setWordWrap(True)
        boundary.setProperty("mutedText", True)
        layout.addWidget(boundary)

    def _refresh_device_selector(self, selector: QComboBox) -> None:
        selected = self._service.selected_device_id()
        selector.clear()
        for device_id in self._service.device_ids():
            selector.addItem(device_id, device_id)
        if selected:
            selector.setCurrentIndex(selector.findData(selected))

    def _bind_current_device(self) -> None:
        confirmation = self.findChild(QLineEdit, "engineeringMaintenanceConfirmation")
        device_id = self.findChild(QLineEdit, "engineeringMaintenanceDeviceId")
        selector = self.findChild(QComboBox, "engineeringMaintenanceDeviceSelector")
        status = self.findChild(QLabel, "engineeringMaintenanceStatus")
        assert confirmation is not None
        assert device_id is not None
        assert selector is not None
        assert status is not None
        candidate = device_id.text().strip() or str(selector.currentData() or "")
        try:
            self._service.bind_current_device(confirmation.text(), candidate)
        except EngineeringMaintenanceAccessDenied:
            status.setText("工程确认未通过，未绑定设备。")
            return
        except EngineeringMaintenanceDeviceUnbound:
            status.setText("设备绑定信息无效，未读取掩码。")
            return
        except ValueError:
            status.setText("请输入有效的设备资产编号。")
            return
        except EngineeringMaintenanceConnectionUnavailable:
            status.setText("当前连接缺少可验证的设备身份，未绑定设备。")
            return
        finally:
            confirmation.clear()
        device_id.clear()
        self._refresh_device_selector(selector)
        status.setText("已绑定当前连接设备；可确认后查看该设备的坏点分布。")

    def _load_distribution(self) -> None:
        confirmation = self.findChild(QLineEdit, "engineeringMaintenanceConfirmation")
        status = self.findChild(QLabel, "engineeringMaintenanceStatus")
        distribution = self.findChild(
            _DefectDistributionWidget, "engineeringDefectDistribution"
        )
        summary = self.findChild(QLabel, "engineeringMaintenanceSummary")
        assert confirmation is not None
        assert status is not None
        assert distribution is not None
        assert summary is not None
        try:
            snapshot = self._service.read_distribution(confirmation.text())
        except EngineeringMaintenanceAccessDenied:
            status.setText("工程确认未通过，未读取设备掩码。")
            return
        except EngineeringMaintenanceDeviceUnbound:
            status.setText("当前连接与所选设备不匹配，无法查看分布。")
            return
        except ValueError:
            status.setText("已绑定设备的掩码不可读取，请按工程流程处理。")
            return
        finally:
            confirmation.clear()
        distribution.set_snapshot(snapshot)
        summary.setText(
            f"黄色 SUSPECT {snapshot.status_counts[DynamicDefectStatus.SUSPECT]}"
            f" · 红色 REPAIRABLE {snapshot.status_counts[DynamicDefectStatus.REPAIRABLE]}"
        )
        status.setText(
            f"已读取绑定设备 {snapshot.device_id} 的掩码版本 {snapshot.mask_version} · {snapshot.health_status.value}"
        )


class _SessionDeletionDialog(QDialog):
    """A deliberately narrow operator-confirmed single-session deletion UI."""

    def __init__(self, service: CompletedSessionDeletionService, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("sessionDeletionDialog")
        self.setWindowTitle("本地会话清理")
        self.setModal(True)
        self.setMinimumWidth(560)
        self._service = service
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(12)
        layout.addWidget(QLabel("本地会话清理（单次操作）"))
        note = QLabel("仅可删除没有保留报告的已完成有效会话。此操作不会批量、定时或因网络确认自动执行。")
        note.setWordWrap(True)
        layout.addWidget(note)
        selector = QComboBox()
        selector.setObjectName("sessionDeletionSelector")
        for session_id in service.candidates():
            selector.addItem(session_id, session_id)
        layout.addWidget(selector)
        confirmation = QLineEdit()
        confirmation.setObjectName("sessionDeletionConfirmation")
        confirmation.setPlaceholderText("输入：删除 <会话编号>")
        layout.addWidget(confirmation)
        confirm = QPushButton("确认删除此会话")
        confirm.setObjectName("CONFIRM_SESSION_DELETION")
        confirm.clicked.connect(self._delete_selected)
        layout.addWidget(confirm, alignment=Qt.AlignmentFlag.AlignLeft)
        status = QLabel("请选择会话并完成确认；不会删除其他会话。")
        status.setObjectName("sessionDeletionStatus")
        status.setWordWrap(True)
        layout.addWidget(status)
        self._refresh_empty_state()

    def _refresh_empty_state(self) -> None:
        selector = self.findChild(QComboBox, "sessionDeletionSelector")
        confirm = self.findChild(QPushButton, "CONFIRM_SESSION_DELETION")
        status = self.findChild(QLabel, "sessionDeletionStatus")
        assert selector is not None and confirm is not None and status is not None
        if selector.count() == 0:
            selector.setEnabled(False)
            confirm.setEnabled(False)
            status.setText("没有可人工删除的已完成有效会话。")

    def _delete_selected(self) -> None:
        selector = self.findChild(QComboBox, "sessionDeletionSelector")
        confirmation = self.findChild(QLineEdit, "sessionDeletionConfirmation")
        status = self.findChild(QLabel, "sessionDeletionStatus")
        assert selector is not None and confirmation is not None and status is not None
        session_id = str(selector.currentData())
        try:
            self._service.delete(session_id=session_id, confirmation=confirmation.text())
        except SessionDeletionConfirmationRequired:
            status.setText(f"未删除。请输入“删除 {session_id}”后再确认。")
            return
        except (ValueError, FileNotFoundError, RuntimeError):
            status.setText("此会话当前不可删除，请刷新后重试或联系技术支持。")
            return
        confirmation.clear()
        selector.removeItem(selector.currentIndex())
        self._refresh_empty_state()
        status.setText("已删除该本地会话；未影响其他会话。")


class _SessionLockOverlay(QFrame):
    def __init__(
        self,
        controller: SessionLockController,
        parent: QWidget,
    ) -> None:
        super().__init__(parent)
        self._controller = controller
        self.setObjectName("sessionLockOverlay")
        self.setStyleSheet(
            "QFrame#sessionLockOverlay { background: #F8FAFC; border: 0; }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.addStretch(1)
        card = QFrame()
        card.setObjectName("sessionLockCard")
        card.setFixedWidth(420)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(32, 32, 32, 32)
        title = QLabel("机构会话已锁定")
        title.setObjectName("sessionLockTitle")
        title.setStyleSheet("font-size: 24px; font-weight: 600;")
        card_layout.addWidget(title)
        note = QLabel("患者、检测与报告内容已隐藏。输入机构账号密码后继续。")
        note.setWordWrap(True)
        note.setProperty("secondaryText", True)
        card_layout.addWidget(note)
        password = QLineEdit()
        password.setObjectName("sessionUnlockPassword")
        password.setEchoMode(QLineEdit.EchoMode.Password)
        password.setPlaceholderText("机构账号密码")
        card_layout.addWidget(password)
        notice = QLabel()
        notice.setObjectName("sessionUnlockNotice")
        notice.setStyleSheet("color: #C23B3B;")
        notice.hide()
        card_layout.addWidget(notice)
        unlock = QPushButton("解锁")
        unlock.setObjectName("UNLOCK_INSTITUTION_SESSION")
        unlock.setProperty("importance", "primary")
        unlock.clicked.connect(self._unlock)
        card_layout.addWidget(unlock)
        layout.addWidget(card, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch(1)
        self.hide()

    def show_locked(self) -> None:
        self.setGeometry(self.parentWidget().rect())
        self.show()
        self.raise_()
        self.findChild(QLineEdit, "sessionUnlockPassword").setFocus()

    def _unlock(self) -> None:
        password = self.findChild(QLineEdit, "sessionUnlockPassword")
        notice = self.findChild(QLabel, "sessionUnlockNotice")
        if self._controller.unlock(password.text()):
            password.clear()
            notice.hide()
            self.hide()
            return
        password.clear()
        notice.setText("密码未通过验证，请稍后重试。")
        notice.show()


class _SessionActivityFilter(QObject):
    _ACTIVITY_EVENTS = {
        QEvent.Type.KeyPress,
        QEvent.Type.MouseButtonPress,
        QEvent.Type.MouseMove,
        QEvent.Type.TouchBegin,
        QEvent.Type.Wheel,
    }

    def __init__(self, window: QMainWindow, controller: SessionLockController) -> None:
        super().__init__(window)
        self._controller = controller

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        del watched
        if event.type() in self._ACTIVITY_EVENTS:
            self._controller.record_activity()
        return False


class ScreeningWindow(QMainWindow):
    """Operator desktop shell faithfully composed from the Steady Health kit."""

    def __init__(
        self,
        *,
        on_action: Callable[[str], None] | None = None,
        physical_grid: PhysicalGridOverlay | None = None,
        session_lock_controller: SessionLockController | None = None,
        protected_operation_active: Callable[[], bool] | None = None,
    ) -> None:
        super().__init__()
        self.setObjectName("screeningWindow")
        self.setWindowTitle("FeetForcePlate 足底压力健康筛查")
        self.setWindowIcon(application_icon())
        self.setMinimumSize(1280, 720)
        self._on_action = on_action
        self._physical_grid = physical_grid
        self._session_lock_controller = session_lock_controller
        self._protected_operation_active = protected_operation_active or (lambda: False)
        self._session_lock_overlay: _SessionLockOverlay | None = None
        self._session_activity_filter: _SessionActivityFilter | None = None
        self._session_lock_timer: QTimer | None = None
        self._stop_confirmation_pending = False
        self._preflight_failed = False
        self._preflight_ready = False
        self._record_rows: tuple[ScreeningRecordRow, ...] = ()
        self._engineering_maintenance_dialog: _EngineeringMaintenanceDialog | None = None
        self._session_deletion_dialog: _SessionDeletionDialog | None = None
        self._pages: dict[PageId, QWidget] = {}
        self._stack = QStackedWidget()
        self._stack.setObjectName("pageStack")
        self._notice_banner = self._banner("noticeBanner")
        self._error_banner = self._banner("errorBanner")
        self._notice_banner.hide()
        self._error_banner.hide()
        self._navigation = QWidget()
        self._navigation.setObjectName("appNavigation")
        self._topbar = self._build_app_header()

        for page_id in PAGE_DEFINITIONS:
            page = self._build_page(page_id)
            self._pages[page_id] = page
            self._stack.addWidget(page)
        self._connect_record_filters()

        content = QWidget()
        content.setObjectName("appSurface")
        root = QVBoxLayout(content)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._topbar)
        root.addWidget(self._notice_banner)
        root.addWidget(self._error_banner)
        root.addWidget(self._stack, 1)
        self.setCentralWidget(content)
        if self._session_lock_controller is not None:
            self._session_lock_overlay = _SessionLockOverlay(
                self._session_lock_controller,
                content,
            )
            self._session_activity_filter = _SessionActivityFilter(
                self,
                self._session_lock_controller,
            )
            self.installEventFilter(self._session_activity_filter)
            for child in self.findChildren(QObject):
                child.installEventFilter(self._session_activity_filter)
            self._session_lock_timer = QTimer(self)
            self._session_lock_timer.setInterval(1_000)
            self._session_lock_timer.timeout.connect(self.evaluate_session_lock)
            self._session_lock_timer.start()
        apply_design_system(self)
        self.show_page(PageId.WORKBENCH)

    @property
    def page_count(self) -> int:
        return self._stack.count()

    @property
    def current_page_id(self) -> PageId:
        current = self._stack.currentWidget()
        return next(page_id for page_id, page in self._pages.items() if page is current)

    @property
    def global_navigation_enabled(self) -> bool:
        return self._navigation.isEnabled()

    @property
    def error_text(self) -> str:
        return self._error_banner.text()

    @property
    def notice_text(self) -> str:
        return self._notice_banner.text()

    def page_widget(self, page_id: PageId) -> QWidget:
        return self._pages[page_id]

    @property
    def session_locked(self) -> bool:
        return bool(
            self._session_lock_overlay is not None
            and self._session_lock_overlay.isVisible()
        )

    def evaluate_session_lock(self) -> None:
        if self._session_lock_controller is None:
            return
        protected = self._protected_operation_active()
        if (
            self._session_lock_controller.state is LockState.LOCK_PENDING
            and not protected
        ):
            state = self._session_lock_controller.protected_operation_finished()
        else:
            state = self._session_lock_controller.tick(
                SessionActivity.ACQUIRING
                if protected
                else SessionActivity.INTERACTIVE
            )
        if state is LockState.LOCKED and self._session_lock_overlay is not None:
            self._session_lock_overlay.show_locked()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._session_lock_overlay is not None:
            self._session_lock_overlay.setGeometry(self.centralWidget().rect())

    def show_page(self, page_id: PageId) -> None:
        self._stack.setCurrentWidget(self._pages[page_id])
        self._topbar.setVisible(page_id in _TOPBAR_PAGES)
        self._set_active_navigation(page_id)

    def present_state(self, state: WorkflowState) -> None:
        page_id = page_for_step(state.step)
        self.show_page(page_id)
        self._navigation.setEnabled(PAGE_DEFINITIONS[page_id].global_navigation_enabled)
        if page_id is not PageId.ACQUIRING:
            self._reset_stop_confirmation()
        if state.position_guidance is not None:
            page = self._pages[PageId.POSITION_GUIDANCE]
            page.findChild(QLabel, "positionGuideTitle").setText(
                state.stage_title or "请站到压力垫中央"
            )
            page.findChild(QLabel, "positionGuideSubtitle").setText(
                state.position_guidance.instruction_text
            )
            page.findChild(QLabel, "positionStatus").setText(
                state.position_guidance.instruction_text
            )
            countdown = page.findChild(QLabel, "countdownLabel")
            has_countdown = state.position_guidance.countdown_seconds is not None
            countdown.setText(
                str(state.position_guidance.countdown_seconds) if has_countdown else ""
            )
            countdown.setVisible(has_countdown)
            page.findChild(QLabel, "positionState").setText(
                state.position_guidance.countdown_text
                if has_countdown
                else "操作员确认站位和安全后，点击开始本段"
            )
            page.findChild(QPushButton, "START_ACQUISITION").setEnabled(
                state.position_guidance.manual_start_allowed
            )
            if state.stage_index is not None and state.stage_count is not None:
                page.findChild(StageGuidanceWidget, "stageGuidance").set_stage(
                    state.stage_index
                )
                page.findChild(QLabel, "positionStage").setText(
                    f"第 {state.stage_index}/{state.stage_count} 段 · "
                    f"{state.stage_title or '当前动作'}"
                )
            page.findChild(QLabel, "positionSource").setText(
                "回放调试数据"
                if state.data_source_mode == "REPLAY_DEBUG"
                else "设备实时采集"
            )
        if state.acquisition_instruction is not None:
            page = self._pages[PageId.ACQUIRING]
            page.findChild(QLabel, "acquisitionInstruction").setText(
                state.acquisition_instruction
            )
            page.findChild(QLabel, "acquisitionStatus").setText("正在采集")
            stage = page.findChild(QLabel, "acquisitionStage")
            if state.stage_index is not None and state.stage_count is not None:
                stage.setText(
                    f"第 {state.stage_index}/{state.stage_count} 段 · "
                    f"{state.stage_title or '当前动作'}"
                )
            source = page.findChild(QLabel, "acquisitionSource")
            source.setText(
                "回放调试数据"
                if state.data_source_mode == "REPLAY_DEBUG"
                else "设备实时采集"
            )
        if state.remaining_seconds is not None:
            minutes, seconds = divmod(state.remaining_seconds, 60)
            page = self._pages[PageId.ACQUIRING]
            page.findChild(QLabel, "remainingTime").setText(
                f"剩余 {minutes:02d}:{seconds:02d}"
            )
            page.findChild(QLabel, "remainingSeconds").setText(str(state.remaining_seconds))
            page.findChild(QProgressBar, "acquisitionProgress").setValue(
                max(
                    0,
                    min(
                        100,
                        int(
                            (1 - state.remaining_seconds /
                             (state.planned_duration_seconds or 20)) * 100
                        ),
                    ),
                )
            )
        if page_id is PageId.PREFLIGHT:
            self._present_preflight_state(state)
        if page_id is PageId.RESULT:
            self._present_result_state(state)
        self._present_banners(state)

    def show_form_error(self, message: str) -> None:
        self._error_banner.setText(message)
        self._error_banner.show()

    def set_subject_match_summary(self, message: str) -> None:
        page = self._pages[PageId.SUBJECT_IDENTIFICATION]
        conflict = page.findChild(QFrame, "subjectConflictView")
        match = page.findChild(QFrame, "matchCard")
        is_conflict = any(
            marker in message
            for marker in ("多个", "多条", "不能自动", "不会自动合并")
        )
        if not is_conflict:
            subject_id = page.findChild(QLabel, "subjectMatchId")
            details = page.findChild(QLabel, "subjectMatchSummary")
            parts = [
                part.strip()
                for part in message.removeprefix("已找到唯一档案：").split("·")
                if part.strip()
            ]
            if parts and parts[0].startswith("编号"):
                subject_id.setText(parts[0].replace("**", "＊＊"))
                details.setText("　".join(parts[1:]))
            else:
                details.setText(message)
        conflict.setVisible(is_conflict)
        match.setVisible(not is_conflict)
        page.findChild(QFrame, "wizardStepBar").setVisible(not is_conflict)
        page.findChild(QLabel, "wizardTitle").setText(
            "档案冲突确认" if is_conflict else "受试者信息"
        )
        page.findChild(QPushButton, "BACK").setText(
            "← 返回" if is_conflict else "← 返回工作台"
        )

    def show_subject_conflict(self) -> None:
        """Expose the design's controlled, never-auto-merge conflict state."""
        self.set_subject_match_summary("同一机构编号存在多条档案，系统不会自动合并。")

    def subject_identifier(self) -> tuple[str, str]:
        page = self._pages[PageId.SUBJECT_IDENTIFICATION]
        return (
            str(page.findChild(QComboBox, "subjectIdTypeInput").currentData()),
            page.findChild(QLineEdit, "subjectExternalIdInput").text(),
        )

    def profile_form_values(self) -> dict[str, tuple[str, str]]:
        page = self._pages[PageId.PROFILE]
        values: dict[str, tuple[str, str]] = {}
        for field_name in (
            "ageBand",
            "sex",
            "height",
            "weight",
            "conditionTags",
            "injuryTags",
        ):
            state = page.findChild(QComboBox, f"{field_name}State")
            value_widget = page.findChild(QWidget, f"{field_name}Input")
            if isinstance(value_widget, QComboBox):
                raw = value_widget.currentData()
                value = "" if raw is None else str(raw)
            elif isinstance(value_widget, QLineEdit):
                value = value_widget.text()
            else:
                raise RuntimeError(f"missing profile input: {field_name}")
            values[field_name] = (str(state.currentData()), value)
        return values

    def _sync_condition_chips(self, clicked: QPushButton) -> None:
        page = self._pages[PageId.PROFILE]
        chips = [
            button
            for button in page.findChildren(QPushButton)
            if button.property("profileChip")
        ]
        missing = next(button for button in chips if button.text() == "未提供")
        if clicked is missing and clicked.isChecked():
            for button in chips:
                if button is not missing:
                    button.setChecked(False)
        elif clicked.isChecked():
            missing.setChecked(False)

        selected = [
            button.text()
            for button in chips
            if button is not missing and button.isChecked()
        ]
        state = page.findChild(QComboBox, "conditionTagsState")
        value = page.findChild(QLineEdit, "conditionTagsInput")
        if missing.isChecked():
            state.setCurrentIndex(state.findData("NONE_REPORTED"))
            value.clear()
        elif selected:
            state.setCurrentIndex(state.findData("PROVIDED"))
            value.setText(",".join(selected))
        else:
            state.setCurrentIndex(state.findData("UNKNOWN"))
            value.clear()

    def consent_choices(self) -> tuple[bool, bool]:
        page = self._pages[PageId.CONSENT]
        return (
            page.findChild(QCheckBox, "requiredConsent").isChecked(),
            page.findChild(QCheckBox, "researchConsent").isChecked(),
        )

    def present_display_frame(self, frame: DisplayFrame) -> None:
        page = self._pages[PageId.ACQUIRING]
        page.findChild(HeatmapWidget, "heatmapHost").set_display_frame(frame)
        if frame.cop_x is None or frame.cop_y is None:
            cop = "COP：等待有效接触"
        else:
            cop = f"COP：({frame.cop_x:.1f}, {frame.cop_y:.1f}) 传感器索引"
        page.findChild(QLabel, "copSummary").setText(cop)
        page.findChild(QLabel, "loadSummary").setText(
            f"相对负重：左 {frame.left_load_percent:.1f}% / 右 {frame.right_load_percent:.1f}%"
        )
        page.findChild(QLabel, "frameFreshness").setText(
            f"设备帧 #{frame.sequence}；显示只取最新帧"
        )

    def present_dashboard(self, snapshot: DashboardSnapshot) -> None:
        self.findChild(QLabel, "organizationName").setText(snapshot.organization_name)
        self._set_pill_text("deviceStatusBadge", snapshot.device_status)
        self._set_pill_text("syncStatusBadge", snapshot.sync_status)
        records = self._pages[PageId.WORKBENCH].findChild(QTableWidget, "recentScreenings")
        self._populate_record_table(records, snapshot.recent_records[:5])
        self._set_recent_table_height(records, len(snapshot.recent_records[:5]))
        self._pages[PageId.WORKBENCH].findChild(QLabel, "recentCount").setText(
            f"今日 {len(snapshot.recent_records)} 条 · 完整列表进入检测记录"
        )

    def present_records(self, records: tuple[ScreeningRecordRow, ...]) -> None:
        self._record_rows = records
        self._refresh_records_table()

    def present_support(self, snapshot: SupportSnapshot) -> None:
        page = self._pages[PageId.SUPPORT]
        page.findChild(QLabel, "deviceHealth").setText(snapshot.device_status)
        page.findChild(QLabel, "syncHealth").setText(snapshot.sync_status)
        page.findChild(QLabel, "pendingCount").setText(
            snapshot.pending_summary.removeprefix("待同步数据：").strip()
        )
        page.findChild(QLabel, "appVersion").setText(snapshot.app_version)

    def set_engineering_maintenance_available(self, available: bool) -> None:
        """Expose maintenance only when deployment supplies trusted wiring."""

        entry = self._pages[PageId.SUPPORT].findChild(
            QPushButton, "OPEN_ENGINEERING_MAINTENANCE"
        )
        assert entry is not None
        entry.setVisible(available)

    def set_session_deletion_available(self, available: bool) -> None:
        entry = self._pages[PageId.SUPPORT].findChild(
            QPushButton, "OPEN_SESSION_DELETION"
        )
        assert entry is not None
        entry.setVisible(available)

    def show_engineering_maintenance(self, service: EngineeringMaintenanceService) -> None:
        """Open a separately confirmed, read-only engineering projection."""

        dialog = _EngineeringMaintenanceDialog(service, self)
        self._engineering_maintenance_dialog = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def show_session_deletion(self, service: CompletedSessionDeletionService) -> None:
        dialog = _SessionDeletionDialog(service, self)
        self._session_deletion_dialog = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def request_live_stage_attestations(
        self,
        *,
        on_confirm: Callable[[tuple[bool, ...]], None],
        on_decline: Callable[[], None],
    ) -> None:
        """Ask the supervising operator, in UI, rather than infer stage outcomes."""

        dialog = QDialog(self)
        dialog.setObjectName("liveStageAttestationDialog")
        dialog.setWindowTitle("确认现场完成情况")
        dialog.setModal(True)
        dialog.setMinimumWidth(640)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.addWidget(QLabel("请由现场工作人员逐段确认"))
        note = QLabel(
            "只有四段均在持续看护下完整完成，且无扶持、失衡或提前睁眼，才会生成基础报告。"
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        labels = (
            "第一段：并足睁眼",
            "第二段：并足闭眼",
            "第三段：左脚在前半串联",
            "第四段：右脚在前半串联",
        )
        boxes: list[QCheckBox] = []
        for index, text in enumerate(labels, start=1):
            box = QCheckBox(f"{text} 已完整完成")
            box.setObjectName(f"liveStageAttestation{index}")
            boxes.append(box)
            layout.addWidget(box)
        actions = QHBoxLayout()
        decline = QPushButton("未全部完成，不生成报告")
        decline.setObjectName("DECLINE_LIVE_STAGE_ATTESTATIONS")
        confirm = QPushButton("确认并生成基础报告")
        confirm.setObjectName("CONFIRM_LIVE_STAGE_ATTESTATIONS")
        confirm.setEnabled(False)
        for box in boxes:
            box.toggled.connect(lambda _checked: confirm.setEnabled(all(item.isChecked() for item in boxes)))
        decline.clicked.connect(lambda: (dialog.reject(), on_decline()))
        confirm.clicked.connect(
            lambda: (dialog.accept(), on_confirm(tuple(item.isChecked() for item in boxes)))
        )
        actions.addWidget(decline)
        actions.addStretch(1)
        actions.addWidget(confirm)
        layout.addLayout(actions)
        self._live_stage_attestation_dialog = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def present_report_document(self, document: BasicReportDocument) -> None:
        page = self._pages[PageId.REPORT_PREVIEW]
        replay_debug = document.kind == "V1_REPLAY_DEBUG"
        basic = document.kind.upper() == "BASIC"
        title = (
            "V1 回放调试报告"
            if replay_debug
            else "基础筛查报告"
            if basic
            else "完整分析报告"
        )
        version_label = "调试版" if replay_debug else "基础版" if basic else "完整版"
        page.findChild(QLabel, "reportPreviewTitle").setText(title)
        page.findChild(QLabel, "reportVersionPillText").setText(
            f"{version_label} v{document.version}"
        )
        page.findChild(QLabel, "reportPreviewMeta").setText(
            f"机构编号 {document.subject_display_id}　·　生成时间 "
            f"{document.generated_at:%Y-%m-%d %H:%M}　·　报告编号 {document.report_id}"
        )
        page.findChild(QLabel, "reportDocumentTitle").setText(
            "足底压力回放调试报告"
            if replay_debug
            else "足底压力基础筛查报告"
            if basic
            else "足底压力健康筛查报告"
        )
        page.findChild(QLabel, "reportDocumentSubtitle").setText(
            "回放调试数据 · 调试分析版"
            if replay_debug
            else "康健社区健康服务中心 · 基础分析版"
            if basic
            else "康健社区健康服务中心 · 完整分析版"
        )
        page.findChild(QLabel, "reportDocumentMeta").setText(
            f"受试者编号　{document.subject_display_id}　　　 "
            f"测试时间　{document.captured_at:%Y-%m-%d %H:%M}\n"
            f"测试项目　{'四段 V1 回放' if replay_debug else '静态筛查'}　　　　 "
            f"报告版本　{'调试' if replay_debug else '基础' if basic else '完整'} "
            f"v{document.version}"
        )
        primary_badge, secondary_badge = report_badges(document.kind)
        page.findChild(QLabel, "reportAttentionText").setText(primary_badge)
        page.findChild(QLabel, "reportRetestText").setText(secondary_badge)
        page.findChild(QLabel, "reportUpdated").setVisible(not replay_debug and not basic)
        page.findChild(QLabel, "reportPreviewSummary").setText(document.summary)
        page.findChild(QLabel, "reportPreviewMetrics").setText(
            " · ".join(
                f"{metric.label} {metric.value:.1f}{'%' if metric.unit == 'percent' else metric.unit}"
                for metric in document.metrics
            )
        )
        page.findChild(QLabel, "reportParameters").setText(
            report_parameter_note(document.kind)
        )
        page.findChild(QLabel, "reportPreviewFooter").setText(
            f"报告编号 {document.report_id} · v{document.version} · 生成 {document.generated_at:%Y-%m-%d %H:%M} · {document.disclaimer}"
        )

    def _present_banners(self, state: WorkflowState) -> None:
        if state.notice is None:
            self._notice_banner.hide()
        else:
            self._notice_banner.setText(state.notice)
            self._notice_banner.show()
        # P-05 renders its actionable failure inside the checklist row, as in
        # the source screen.  Repeating it in the global banner changes the
        # page geometry and presents the same error twice.
        if state.error is None or self.current_page_id is PageId.PREFLIGHT:
            self._error_banner.hide()
        else:
            self._error_banner.setText(
                f"{state.error.operator_message}（错误编号：{state.error.code}）"
            )
            self._error_banner.show()

    def _refresh_records_table(self) -> None:
        page = self._pages[PageId.RECORDS]
        query = page.findChild(QLineEdit, "recordSearchInput").text().strip()
        status_filter = str(page.findChild(QComboBox, "recordStatusFilter").currentData())
        date_filter = str(page.findChild(QComboBox, "recordDateFilter").currentData())
        rows = tuple(
            record
            for record in self._record_rows
            if (not query or query.casefold() in record.subject_display_id.casefold())
            and (not status_filter or record.report_status_label == status_filter)
            and (date_filter != "today" or record.performed_on == date.today())
        )
        table = page.findChild(QTableWidget, "recordsTable")
        self._populate_record_table(table, rows)

    def _populate_record_table(
        self,
        table: QTableWidget,
        rows: tuple[ScreeningRecordRow, ...],
    ) -> None:
        table.clearContents()
        table.setRowCount(len(rows))
        for row_index, record in enumerate(rows):
            values = (
                record.subject_display_id,
                record.screening_label,
                record.performed_at_label,
                record.report_status_label,
                "查看",
            )
            for column, value in enumerate(values):
                table.setItem(row_index, column, QTableWidgetItem(value))
            tone = (
                "success"
                if record.report_status_label in {"完整报告", "基础报告"}
                else "info"
                if record.report_status_label in {"分析中", "生成中"}
                else "neutral"
                if record.report_status_label == "调试报告"
                else "danger"
            )
            host = QWidget()
            host.setAccessibleName(record.report_status_label)
            host_layout = QHBoxLayout(host)
            host_layout.setContentsMargins(8, 0, 8, 0)
            host_layout.addWidget(
                self._status_pill(
                    f"{table.objectName()}Status{row_index}",
                    record.report_status_label,
                    tone,
                ),
                alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            )
            table.setCellWidget(row_index, 3, host)
            # The semantic status is rendered by the pill; retain an empty item
            # below it only so the model stays inspectable without duplicate text.
            table.item(row_index, 3).setText("")
            view = QPushButton("查看")
            view.setObjectName(f"{table.objectName()}View{row_index}")
            view.setProperty("importance", "ghost")
            if record.report_id is None or record.report_version is None:
                view.setEnabled(False)
                view.setToolTip("报告尚不可用")
            else:
                view.clicked.connect(
                    lambda _checked=False, report_id=record.report_id,
                    version=record.report_version: self._dispatch(
                        f"OPEN_REPORT:{report_id}:{version}"
                    )
                )
            table.setCellWidget(row_index, 4, view)
            table.item(row_index, 4).setText("")

    def _connect_record_filters(self) -> None:
        page = self._pages[PageId.RECORDS]
        page.findChild(QLineEdit, "recordSearchInput").textChanged.connect(
            lambda _text: self._refresh_records_table()
        )
        page.findChild(QComboBox, "recordStatusFilter").currentIndexChanged.connect(
            lambda _index: self._refresh_records_table()
        )
        page.findChild(QComboBox, "recordDateFilter").currentIndexChanged.connect(
            lambda _index: self._refresh_records_table()
        )

    def _build_app_header(self) -> QFrame:
        header = QFrame()
        header.setObjectName("appHeader")
        layout = QHBoxLayout(header)
        layout.setContentsMargins(32, 0, 32, 0)
        layout.setSpacing(16)
        layout.addWidget(self._brand_logo(28))
        divider = QLabel()
        divider.setObjectName("brandDivider")
        layout.addWidget(divider)
        organization = QLabel("康健社区健康服务中心")
        organization.setObjectName("organizationName")
        organization.setAccessibleName("当前机构")
        layout.addWidget(organization)
        layout.addStretch(1)
        navigation = QHBoxLayout(self._navigation)
        navigation.setContentsMargins(0, 0, 0, 0)
        navigation.setSpacing(24)
        for page_id, label in (
            (PageId.WORKBENCH, "工作台"),
            (PageId.RECORDS, "检测记录"),
            (PageId.SUPPORT, "设备与支持"),
        ):
            button = QPushButton(label)
            button.setObjectName(f"nav{page_id.value}")
            button.setAccessibleName(label)
            button.setProperty("navigationPage", page_id.value)
            button.clicked.connect(lambda _checked=False, page=page_id: self.show_page(page))
            navigation.addWidget(button)
        layout.addWidget(self._navigation)
        layout.addStretch(1)
        layout.addWidget(self._status_pill("deviceStatusBadge", "设备已就绪", "success"))
        layout.addWidget(self._status_pill("syncStatusBadge", "网络正常", "success"))
        return header

    def _set_active_navigation(self, page_id: PageId) -> None:
        active_page = page_id if page_id in {PageId.WORKBENCH, PageId.RECORDS, PageId.SUPPORT} else PageId.WORKBENCH
        for button in self._navigation.findChildren(QPushButton):
            button.setProperty("activeNavigation", button.property("navigationPage") == active_page.value)
            button.style().unpolish(button)
            button.style().polish(button)

    @staticmethod
    def _banner(object_name: str) -> QLabel:
        label = QLabel()
        label.setObjectName(object_name)
        label.setWordWrap(True)
        label.setContentsMargins(32, 12, 32, 12)
        return label

    def _status_pill(self, object_name: str, label_text: str, tone: str) -> QFrame:
        pill = QFrame()
        pill.setObjectName(object_name)
        pill.setProperty("statusPill", True)
        pill.setProperty("statusPillTone", tone)
        pill.setAccessibleName(label_text)
        layout = QHBoxLayout(pill)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(8)
        dot = QFrame()
        dot.setProperty("statusDot", True)
        dot.setProperty("statusDotTone", tone)
        layout.addWidget(dot)
        text = QLabel(label_text)
        text.setObjectName(f"{object_name}Text")
        layout.addWidget(text)
        return pill

    def _set_pill_text(self, object_name: str, text: str) -> None:
        self.findChild(QLabel, f"{object_name}Text").setText(text)

    @staticmethod
    def _set_pill_tone(pill: QFrame, tone: str) -> None:
        pill.setProperty("statusPillTone", tone)
        dot = pill.findChild(QFrame)
        if dot is not None:
            dot.setProperty("statusDotTone", tone)
            dot.style().unpolish(dot)
            dot.style().polish(dot)
        pill.style().unpolish(pill)
        pill.style().polish(pill)

    @staticmethod
    def _brand_logo(height: int) -> QLabel:
        logo = QLabel()
        logo.setObjectName("brandLogo")
        logo.setAccessibleName("天富智柔 TechFlex")
        path = Path(__file__).resolve().parents[2] / "docs" / "ui-desgin" / "assets" / "logo-horizontal-trimmed.png"
        pixmap = QPixmap(str(path))
        if not pixmap.isNull():
            logo.setPixmap(pixmap.scaledToHeight(height, Qt.TransformationMode.SmoothTransformation))
        logo.setFixedHeight(height)
        return logo

    def _build_page(self, page_id: PageId) -> QWidget:
        return {
            PageId.WORKBENCH: self._build_workbench_page,
            PageId.SUBJECT_IDENTIFICATION: self._build_subject_page,
            PageId.PROFILE: self._build_profile_page,
            PageId.CONSENT: self._build_consent_page,
            PageId.PREFLIGHT: self._build_preflight_page,
            PageId.POSITION_GUIDANCE: self._build_position_page,
            PageId.ACQUIRING: self._build_acquiring_page,
            PageId.RESULT: self._build_result_page,
            PageId.RECORDS: self._build_records_page,
            PageId.REPORT_PREVIEW: self._build_report_page,
            PageId.SUPPORT: self._build_support_page,
        }[page_id]()

    def _new_page(self, page_id: PageId) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        page.setObjectName(page_id.value)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        return page, layout

    def _build_workbench_page(self) -> QWidget:
        page, layout = self._new_page(PageId.WORKBENCH)
        body = QWidget()
        body.setObjectName("pageCanvas")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)
        content = QWidget()
        # Match the approved desktop workbench grid.  It remains deliberately
        # narrower than the window so the hierarchy reads as a work surface,
        # not a full-bleed prototype page.
        content.setFixedWidth(1120)
        content_layout = QVBoxLayout(content)
        # P-01 uses a 64px page inset, then a 44px hero inset.  Keeping these
        # separate avoids the previous oversized blank band above the title.
        content_layout.setContentsMargins(32, 64, 32, 40)
        content_layout.setSpacing(0)
        hero = QWidget()
        hero.setObjectName("workbenchHero")
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(0, 44, 0, 64)
        hero_layout.setSpacing(0)
        title = self._label("足底压力健康筛查", "pageTitle", alignment=Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 32px;")
        subtitle = self._label("请引导受试者到达压力垫前，准备就绪后开始新的检测。", "pageSubtitle", alignment=Qt.AlignmentFlag.AlignCenter)
        start = self._action_button("START_NEW_SCREENING", primary=True)
        start.setFixedSize(220, 64)
        hero_layout.addWidget(title)
        hero_layout.addSpacing(14)
        hero_layout.addWidget(subtitle)
        hero_layout.addSpacing(40)
        hero_layout.addWidget(start, alignment=Qt.AlignmentFlag.AlignHCenter)
        content_layout.addWidget(hero)
        heading = QHBoxLayout()
        heading.setSpacing(12)
        heading.addWidget(self._label("最近检测", "sectionTitle"))
        heading.addStretch(1)
        count = self._label("今日 0 条 · 完整列表进入检测记录", "recentCount")
        count.setProperty("secondaryText", True)
        heading.addWidget(count)
        content_layout.addLayout(heading)
        content_layout.addSpacing(16)
        recent = self._records_table("recentScreenings")
        recent.setColumnCount(5)
        recent.setHorizontalHeaderLabels(("编号", "测试项目", "时间", "报告状态", ""))
        self._set_recent_table_height(recent, 0)
        content_layout.addWidget(recent)
        content_layout.addStretch(1)
        body_layout.addWidget(content, 1, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(body, 1)
        return page

    def _build_subject_page(self) -> QWidget:
        page, layout = self._new_page(PageId.SUBJECT_IDENTIFICATION)
        layout.addWidget(self._wizard_header("受试者信息", 0, "← 返回工作台"))
        layout.addWidget(self._stepbar(0))
        body, body_layout = self._wizard_body()
        lookup_row = QHBoxLayout()
        lookup_row.setSpacing(12)
        identifier = QLineEdit("2024-0731")
        identifier.setObjectName("subjectExternalIdInput")
        identifier.setAccessibleName("机构档案号、病历号或体检号")
        identifier.setPlaceholderText("机构档案号 / 病历号 / 体检号")
        identifier.setMinimumHeight(48)
        id_type = QComboBox()
        id_type.setObjectName("subjectIdTypeInput")
        id_type.addItem("机构档案号", "institution_record")
        id_type.addItem("病历号", "medical_record_number")
        id_type.addItem("体检号", "examination_number")
        id_type.addItem("住户编号", "resident_number")
        id_type.setVisible(False)
        lookup = QPushButton("查找")
        lookup.setObjectName("lookupSubjectButton")
        lookup.setAccessibleName("查找受试者")
        lookup.setMinimumSize(88, 48)
        lookup.clicked.connect(lambda: self._dispatch("LOOKUP_SUBJECT"))
        lookup_row.addWidget(identifier, 1)
        lookup_row.addWidget(lookup)
        label = self._label("机构档案号 / 病历号 / 体检号", "fieldLabel")
        label.setBuddy(identifier)
        body_layout.addWidget(label)
        body_layout.addSpacing(8)
        subject_lookup = QFrame()
        subject_lookup.setObjectName("subjectLookupRow")
        subject_layout = QHBoxLayout(subject_lookup)
        subject_layout.setContentsMargins(0, 0, 0, 0)
        subject_layout.addLayout(lookup_row)
        subject_layout.addWidget(id_type)
        body_layout.addWidget(subject_lookup)
        hint = self._label("支持扫描枪与手动输入", "subjectHint")
        hint.setProperty("secondaryText", True)
        body_layout.addWidget(hint)
        body_layout.addSpacing(28)
        divider = self._divider_with_text("或")
        body_layout.addWidget(divider)
        body_layout.addSpacing(20)
        create = self._action_button("CREATE_ANONYMOUS_SUBJECT", primary=False, ghost=True)
        create.setMinimumWidth(220)
        body_layout.addWidget(create, alignment=Qt.AlignmentFlag.AlignLeft)
        match = QFrame()
        match.setObjectName("matchCard")
        match_layout = QHBoxLayout(match)
        match_layout.setContentsMargins(24, 20, 24, 20)
        text_column = QVBoxLayout()
        found = self._label("已找到匹配档案", "matchEyebrow")
        found.setProperty("eyebrow", True)
        subject_id = self._label("编号 ＊＊2781", "subjectMatchId")
        subject_id.setStyleSheet(
            "font-size: 20px; font-weight: 600; color: #0F172A;"
        )
        summary = self._label(
            "年龄 64 岁　性别 女　上次检测 07-12",
            "subjectMatchSummary",
        )
        summary.setStyleSheet(
            "font-size: 16px; font-weight: 400; color: #475569;"
        )
        summary.setWordWrap(True)
        summary.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        note = self._label("请核对是否为本人，避免同名或错号档案；如信息不符请返回重新查找。", "matchNote")
        note.setProperty("secondaryText", True)
        note.setStyleSheet("font-size: 16px; font-weight: 400; color: #475569;")
        note.setWordWrap(True)
        note.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        text_column.addWidget(found)
        text_column.addSpacing(6)
        text_column.addWidget(subject_id)
        text_column.addSpacing(6)
        text_column.addWidget(summary)
        text_column.addSpacing(12)
        text_column.addWidget(note)
        match_layout.addLayout(text_column, 1)
        match_layout.addSpacing(24)
        confirm = self._action_button("CONFIRM_SUBJECT", primary=True)
        confirm.setFixedSize(140, 56)
        confirm.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        match_layout.addWidget(confirm, alignment=Qt.AlignmentFlag.AlignVCenter)
        body_layout.addSpacing(32)
        body_layout.addWidget(match)
        conflict = QFrame()
        conflict.setObjectName("subjectConflictView")
        conflict.setVisible(False)
        conflict_layout = QVBoxLayout(conflict)
        conflict_layout.setContentsMargins(0, 0, 0, 0)
        conflict_layout.setSpacing(16)
        conflict_banner = QFrame()
        conflict_banner.setObjectName("subjectConflictBanner")
        conflict_banner_layout = QVBoxLayout(conflict_banner)
        conflict_banner_layout.setContentsMargins(16, 12, 16, 12)
        conflict_banner_layout.setSpacing(4)
        conflict_heading = self._label("发现多个匹配档案", "conflictHeading")
        conflict_heading.setStyleSheet("font-size: 20px; font-weight: 600; color: #96600D;")
        conflict_note = self._label("系统不会自动合并，请人工确认对应受试者后再继续。", "conflictNote")
        conflict_note.setProperty("secondaryText", True)
        conflict_banner_layout.addWidget(conflict_heading)
        conflict_banner_layout.addWidget(conflict_note)
        conflict_layout.addWidget(conflict_banner)
        candidates = QHBoxLayout()
        candidates.setSpacing(16)
        for age, created, tested in (("60–69", "2024-03-11", "07-12"), ("40–49", "2025-09-02", "06-28")):
            candidate = QFrame()
            candidate.setObjectName("contentCard")
            candidate_layout = QVBoxLayout(candidate)
            candidate_layout.setContentsMargins(20, 20, 20, 20)
            candidate_layout.addWidget(self._label("＊＊2781", "conflictCandidateId"))
            candidate_layout.itemAt(0).widget().setStyleSheet("font-size: 20px; font-weight: 600;")
            candidate_detail = self._label(f"年龄段　{age}\n建档时间　{created}\n上次检测　{tested}", "conflictCandidateDetail")
            candidate_detail.setProperty("secondaryText", True)
            candidate_layout.addSpacing(12)
            candidate_layout.addWidget(candidate_detail)
            candidate_layout.addSpacing(20)
            choice = QPushButton("选择此档案")
            choice.setMinimumHeight(48)
            choice.setAccessibleDescription("需由受检者确认后才可继续")
            candidate_layout.addWidget(choice)
            candidates.addWidget(candidate)
        conflict_layout.addLayout(candidates)
        conflict_create = self._action_button("CREATE_ANONYMOUS_SUBJECT", primary=False, ghost=True, label="都不是，以此编号新建档案")
        conflict_layout.addWidget(conflict_create, alignment=Qt.AlignmentFlag.AlignHCenter)
        body_layout.addWidget(conflict)
        body_layout.addStretch(1)
        layout.addWidget(body, 1)
        return page

    def _build_profile_page(self) -> QWidget:
        page, layout = self._new_page(PageId.PROFILE)
        layout.addWidget(self._wizard_header("基础信息（选填）", 1))
        layout.addWidget(self._stepbar(1))
        body, body_layout = self._wizard_body()
        profile_title = self._label("基础信息（选填，可直接继续）", "pageTitle")
        profile_title.setStyleSheet("font-size: 24px; font-weight: 600;")
        body_layout.addWidget(profile_title)
        lead = self._label("以下信息用于提高分析参考性，可跳过；标签为「本人/机构提供」，不作为临床确诊。", "profileLead")
        lead.setProperty("secondaryText", True)
        lead.setWordWrap(True)
        body_layout.addSpacing(8)
        body_layout.addWidget(lead)
        body_layout.addSpacing(28)
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(24)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        age = self._profile_combo("ageBandInput", "年龄段（选填）", (("60–69", "60-69"), ("请选择 / 不提供", None)))
        sex = self._profile_combo("sexInput", "性别（选填）", (("请选择 / 不提供", None), ("女", "female"), ("男", "male")))
        height = self._field_with_unit("heightInput", "身高", "cm", "162")
        weight = self._field_with_unit("weightInput", "体重", "kg", "58")
        grid.addWidget(self._field_group("年龄段", age), 0, 0)
        grid.addWidget(self._field_group("性别", sex), 0, 1)
        grid.addWidget(height, 1, 0)
        grid.addWidget(weight, 1, 1)
        body_layout.addLayout(grid)
        body_layout.addSpacing(28)
        body_layout.addWidget(self._label("基础情况（本人/机构提供，可多选）", "fieldLabel"))
        chips = QGridLayout()
        chips.setHorizontalSpacing(8)
        chips.setVerticalSpacing(8)
        chip_labels = (
            "高血压",
            "糖尿病",
            "既往下肢损伤",
            "关节炎",
            "周围神经病变",
            "足部手术史",
            "未提供",
        )
        for index, label in enumerate(chip_labels):
            chip = QPushButton(label)
            chip.setObjectName(f"conditionChip{index}")
            chip.setCheckable(True)
            chip.setAutoExclusive(False)
            chip.setProperty("profileChip", True)
            chip.setFixedHeight(40)
            chip.setAccessibleName(f"基础情况：{label}")
            chip.setAccessibleDescription(
                "可多选；选择未提供会清除其他基础情况"
            )
            chip.clicked.connect(
                lambda _checked=False, button=chip: self._sync_condition_chips(
                    button
                )
            )
            chips.addWidget(
                chip,
                index // 4,
                index % 4,
                alignment=Qt.AlignmentFlag.AlignLeft,
            )
        chips.setColumnStretch(4, 1)
        body_layout.addSpacing(8)
        body_layout.addLayout(chips)
        hidden_fields = self._hidden_profile_controls()
        body_layout.addWidget(hidden_fields)
        body_layout.addStretch(1)
        layout.addWidget(body, 1)
        layout.addWidget(self._wizard_footer(("SKIP_PROFILE", "SAVE_PROFILE")))
        return page

    def _build_consent_page(self) -> QWidget:
        page, layout = self._new_page(PageId.CONSENT)
        layout.addWidget(self._wizard_header("数据使用说明", 2))
        layout.addWidget(self._stepbar(2))
        body, body_layout = self._wizard_body()
        consent_title = self._label("数据使用说明", "pageTitle")
        consent_title.setStyleSheet("font-size: 24px; font-weight: 600;")
        body_layout.addWidget(consent_title)
        intro = self._label(
            "本次筛查将采集足底压力和您自愿提供的基础信息，数据会加密上传，用于生成基础及完整分析报告、保存历次记录并保障服务运行。数据在本机构范围内处理，不用于自动诊断。",
            "consentIntro",
        )
        intro.setWordWrap(True)
        intro.setProperty("secondaryText", True)
        body_layout.addSpacing(16)
        body_layout.addWidget(intro)
        policy = self._action_button("VIEW_POLICY", primary=False, ghost=True, label="查看完整信息处理规则")
        policy.setObjectName("policyLink")
        body_layout.addSpacing(20)
        body_layout.addWidget(policy, alignment=Qt.AlignmentFlag.AlignLeft)
        required = QCheckBox("我已了解并同意上述必要处理")
        required.setObjectName("requiredConsent")
        required.setAccessibleName("必要处理授权")
        research = QCheckBox("我同意将去标识化数据用于额外算法研究（选填）")
        research.setObjectName("researchConsent")
        research.setAccessibleName("额外算法研究授权（选填）")
        body_layout.addSpacing(28)
        body_layout.addWidget(required)
        body_layout.addSpacing(20)
        body_layout.addWidget(research)
        note = self._label("拒绝必要处理将无法进入上传型筛查服务；相同有效授权的返回受试者会自动跳过本页。", "consentNote")
        note.setWordWrap(True)
        note.setProperty("mutedText", True)
        body_layout.addSpacing(24)
        body_layout.addWidget(note)
        body_layout.addStretch(1)
        layout.addWidget(body, 1)
        layout.addWidget(self._wizard_footer(("BACK", "CONFIRM_CONSENT"), labels={"BACK": "← 返回"}))
        return page

    def _build_preflight_page(self) -> QWidget:
        page, layout = self._new_page(PageId.PREFLIGHT)
        layout.addWidget(self._wizard_header("正在准备检测", 3))
        layout.addWidget(self._stepbar(3))
        body, body_layout = self._wizard_body()
        checklist = QFrame()
        checklist.setObjectName("checklistCard")
        checks = QVBoxLayout(checklist)
        checks.setContentsMargins(24, 8, 24, 8)
        checks.setSpacing(0)
        for object_name, label, hint in (
            ("deviceCheck", "压力设备", "已连接"),
            ("storageCheck", "数据存储", "空间充足"),
            ("calibrationCheck", "校准状态", "等待检查"),
            ("syncCheck", "数据同步", "已同步"),
            ("zeroLoadCheck", "设备零载", "等待检查"),
        ):
            checks.addWidget(self._checklist_item(object_name, label, hint, "success"))
        body_layout.addWidget(checklist)
        instruction = self._label("请确保压力垫上暂时无人站立", "preflightInstruction", alignment=Qt.AlignmentFlag.AlignCenter)
        instruction.setProperty("secondaryText", True)
        note = self._label("全部通过后，请点击进入站位引导", "preflightNote", alignment=Qt.AlignmentFlag.AlignCenter)
        note.setProperty("mutedText", True)
        body_layout.addSpacing(32)
        body_layout.addWidget(instruction)
        body_layout.addSpacing(8)
        body_layout.addWidget(note)
        body_layout.addStretch(1)
        layout.addWidget(body, 1)
        layout.addWidget(self._preflight_footer())
        return page

    def _build_position_page(self) -> QWidget:
        page, layout = self._new_page(PageId.POSITION_GUIDANCE)
        layout.addWidget(self._wizard_header("站位引导", None, "← 取消"))
        body = QWidget()
        body.setObjectName("pageCanvas")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(32, 32, 32, 32)
        body_layout.setSpacing(0)
        title = self._label("请站到压力垫中央", "positionGuideTitle", alignment=Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 40px;")
        title.setFixedHeight(48)
        subtitle = self._label("双脚自然站立，保持身体放松，目视前方", "positionGuideSubtitle", alignment=Qt.AlignmentFlag.AlignCenter)
        subtitle.setFixedHeight(28)
        stage = self._label("第 --/-- 段", "positionStage", alignment=Qt.AlignmentFlag.AlignCenter)
        stage.setStyleSheet("font-size: 16px; font-weight: 600; color: #1E293B;")
        source = self._label("设备实时采集", "positionSource", alignment=Qt.AlignmentFlag.AlignCenter)
        source.setProperty("secondaryText", True)
        body_layout.addWidget(title)
        body_layout.addSpacing(8)
        body_layout.addWidget(subtitle)
        body_layout.addSpacing(4)
        body_layout.addWidget(stage)
        body_layout.addSpacing(2)
        body_layout.addWidget(source)
        body_layout.addSpacing(20)
        guide = StageGuidanceWidget()
        guide.setMaximumHeight(320)
        body_layout.addWidget(guide, 1, alignment=Qt.AlignmentFlag.AlignHCenter)
        details_host = QWidget()
        details_host.setFixedWidth(520)
        details = QHBoxLayout(details_host)
        details.setContentsMargins(0, 0, 0, 0)
        details.setSpacing(24)
        status_column = QVBoxLayout()
        status_column.setContentsMargins(0, 0, 0, 0)
        status = self._label("请按指引调整站位，准备好后开始本段", "positionStatus")
        status.setProperty("secondaryText", True)
        count_line = QHBoxLayout()
        count_line.addWidget(
            self._label("操作员确认站位和安全后，点击开始本段", "positionState")
        )
        countdown = self._label("", "countdownLabel")
        countdown.setStyleSheet("font-size: 48px; font-weight: 700; color: #2569BC;")
        count_line.addWidget(countdown)
        count_line.addStretch(1)
        status_column.addWidget(status)
        status_column.addSpacing(4)
        status_column.addLayout(count_line)
        status_host = QWidget()
        status_host.setFixedWidth(300)
        status_host.setLayout(status_column)
        details.addWidget(status_host)
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.VLine)
        separator.setStyleSheet("color: #E2E8F0;")
        separator.setFixedHeight(48)
        details.addWidget(separator)
        manual = self._action_button("START_ACQUISITION", primary=True)
        manual.setMinimumSize(130, 56)
        manual.setEnabled(False)
        details.addWidget(manual)
        body_layout.addSpacing(32)
        body_layout.addWidget(details_host, alignment=Qt.AlignmentFlag.AlignHCenter)
        body_layout.addStretch(1)
        layout.addWidget(body, 1)
        return page

    def _build_acquiring_page(self) -> QWidget:
        page, layout = self._new_page(PageId.ACQUIRING)
        header = QFrame()
        header.setObjectName("screeningHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(32, 0, 32, 0)
        header_layout.addWidget(self._label("检测进行中", "screeningTitle"))
        header_layout.addStretch(1)
        remaining_label = self._label("剩余", "remainingPrefix")
        remaining_label.setProperty("secondaryText", True)
        remaining_label.hide()
        header_layout.addWidget(remaining_label)
        time = self._label("剩余 00:--", "remainingTime")
        time.setStyleSheet("font-size: 20px; font-weight: 600; margin-left: 8px;")
        header_layout.addWidget(time)
        layout.addWidget(header)
        content = QFrame()
        content.setObjectName("acquisitionContent")
        content_layout = QHBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(32, 32, 32, 32)
        heatmap = HeatmapWidget(physical_grid=self._physical_grid)
        heatmap.setMinimumHeight(480)
        left_layout.addWidget(heatmap, 1)
        content_layout.addWidget(left, 3)
        side = QFrame()
        side.setObjectName("acquisitionInstructionsCard")
        side.setStyleSheet("border-left: 1px solid #E2E8F0; border-radius: 0;")
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(32, 48, 32, 32)
        side_layout.setSpacing(0)
        side_layout.addStretch(1)
        status = self._label("正在采集", "acquisitionStatus")
        status.setStyleSheet("font-size: 14px; font-weight: 600; color: #2569BC; letter-spacing: 2px;")
        stage = self._label("第 --/-- 段", "acquisitionStage")
        stage.setStyleSheet("font-size: 16px; font-weight: 600; color: #1E293B;")
        source = self._label("设备实时采集", "acquisitionSource")
        source.setProperty("secondaryText", True)
        instruction = self._label("请保持自然站立，\n不要说话或大幅移动。", "acquisitionInstruction")
        instruction.setStyleSheet("font-size: 24px; font-weight: 600; line-height: 1.5;")
        seconds = self._label("--", "remainingSeconds")
        seconds.setStyleSheet("font-size: 96px; font-weight: 700; color: #2569BC;")
        seconds_caption = self._label("剩余采集时间（秒）", "secondsCaption")
        seconds_caption.setProperty("secondaryText", True)
        progress = QProgressBar()
        progress.setObjectName("acquisitionProgress")
        progress.setRange(0, 100)
        progress.setValue(0)
        progress.setTextVisible(False)
        progress.setMaximumWidth(360)
        note = self._label("采集进行中，请勿离开压力垫", "acquisitionNote")
        note.setProperty("secondaryText", True)
        for widget, spacing in ((status, 8), (stage, 4), (source, 16), (instruction, 32), (seconds, 8), (seconds_caption, 32), (progress, 8), (note, 0)):
            side_layout.addWidget(widget)
            if spacing:
                side_layout.addSpacing(spacing)
        accessible_summaries = QWidget(side)
        accessible_summaries.setVisible(False)
        accessible_layout = QVBoxLayout(accessible_summaries)
        accessible_layout.addWidget(self._label("COP：等待有效接触", "copSummary"))
        accessible_layout.addWidget(self._label("相对负重：等待设备帧", "loadSummary"))
        accessible_layout.addWidget(self._label("显示只取最新设备帧", "frameFreshness"))
        side_layout.addWidget(accessible_summaries)
        side_layout.addStretch(1)
        stop = self._action_button("STOP_SCREENING", primary=False)
        stop.setMinimumWidth(110)
        side_layout.addWidget(stop, alignment=Qt.AlignmentFlag.AlignRight)
        content_layout.addWidget(side, 2)
        layout.addWidget(content, 1)

        overlay = QFrame(page)
        overlay.setObjectName("stopConfirmationOverlay")
        overlay.setVisible(False)
        overlay_layout = QVBoxLayout(overlay)
        overlay_layout.setContentsMargins(24, 24, 24, 24)
        overlay_layout.addStretch(1)
        dialog = QFrame()
        dialog.setObjectName("stopConfirmationDialog")
        dialog.setFixedWidth(480)
        dialog_layout = QVBoxLayout(dialog)
        dialog_layout.setContentsMargins(24, 24, 24, 24)
        dialog_layout.setSpacing(0)
        dialog_title = self._label("停止本次检测？", "stopConfirmationTitle")
        dialog_title.setStyleSheet("font-size: 20px; font-weight: 600;")
        dialog_body = self._label(
            "已采集的数据将不生成报告，可立即重新开始。",
            "stopConfirmationBody",
        )
        dialog_body.setProperty("secondaryText", True)
        dialog_layout.addWidget(dialog_title)
        dialog_layout.addSpacing(12)
        dialog_layout.addWidget(dialog_body)
        dialog_layout.addSpacing(24)
        dialog_actions = QHBoxLayout()
        dialog_actions.addStretch(1)
        continue_button = QPushButton("继续检测")
        continue_button.setObjectName("CONTINUE_SCREENING")
        continue_button.setAccessibleName("继续检测")
        continue_button.setMinimumHeight(48)
        continue_button.clicked.connect(self._reset_stop_confirmation)
        confirm_stop = QPushButton("停止检测")
        confirm_stop.setObjectName("CONFIRM_STOP_SCREENING")
        confirm_stop.setAccessibleName("确认停止检测")
        confirm_stop.setProperty("importance", "danger")
        confirm_stop.setMinimumHeight(48)
        confirm_stop.clicked.connect(self._confirm_stop_screening)
        dialog_actions.addWidget(continue_button)
        dialog_actions.addSpacing(12)
        dialog_actions.addWidget(confirm_stop)
        dialog_layout.addLayout(dialog_actions)
        overlay_layout.addWidget(dialog, alignment=Qt.AlignmentFlag.AlignHCenter)
        overlay_layout.addStretch(1)
        return page

    def _build_result_page(self) -> QWidget:
        page, layout = self._new_page(PageId.RESULT)
        content = QWidget()
        content.setObjectName("pageCanvas")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(32, 32, 32, 32)
        content_layout.addStretch(1)
        card = QFrame()
        card.setObjectName("resultCard")
        card.setFixedWidth(560)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(48, 48, 48, 48)
        card_layout.setSpacing(0)
        icon = QFrame()
        icon.setObjectName("resultStatusIcon")
        icon.setFixedSize(72, 72)
        icon.setStyleSheet("background: #EBF7F0; border: 1px solid #BFE5D0; border-radius: 36px;")
        icon_layout = QVBoxLayout(icon)
        icon_layout.setContentsMargins(16, 16, 16, 16)
        success_mark = QSvgWidget()
        success_mark.setObjectName("resultSuccessIcon")
        success_mark.setFixedSize(40, 40)
        success_mark.load(str(self._icon_asset("status-success.svg")))
        icon_layout.addWidget(success_mark)
        card_layout.addWidget(icon, alignment=Qt.AlignmentFlag.AlignHCenter)
        title = self._label("基础报告已生成", "resultTitle", alignment=Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 28px; font-weight: 600;")
        summary = self._label("本次足底压力筛查已完成质量校核，基础报告可立即查看。", "resultSummary", alignment=Qt.AlignmentFlag.AlignCenter)
        summary.setProperty("secondaryText", True)
        summary.setWordWrap(True)
        basic = self._status_pill("basicReportStatus", "基础报告已生成", "success")
        full = self._status_pill("fullReportStatus", "完整分析报告正在后台生成", "info")
        basic.hide()
        actions = QFrame()
        actions.setObjectName("pageActions")
        action_layout = QHBoxLayout(actions)
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.setSpacing(12)
        next_button = self._action_button("START_NEXT_SCREENING", primary=False)
        view_button = self._action_button("VIEW_BASIC_REPORT", primary=True)
        return_button = QPushButton("返回工作台")
        return_button.setObjectName("RETURN_WORKBENCH")
        return_button.setAccessibleName("返回工作台")
        return_button.setMinimumHeight(48)
        return_button.clicked.connect(lambda: self.show_page(PageId.WORKBENCH))
        return_button.hide()
        retry_button = self._action_button("RETRY_SCREENING", primary=True)
        retry_button.hide()
        action_layout.addStretch(1)
        action_layout.addWidget(next_button)
        action_layout.addWidget(view_button)
        action_layout.addWidget(return_button)
        action_layout.addWidget(retry_button)
        action_layout.addStretch(1)
        card_layout.addSpacing(24)
        card_layout.addWidget(title)
        card_layout.addSpacing(12)
        card_layout.addWidget(summary)
        card_layout.addSpacing(24)
        card_layout.addWidget(basic, alignment=Qt.AlignmentFlag.AlignHCenter)
        card_layout.addSpacing(12)
        card_layout.addWidget(full, alignment=Qt.AlignmentFlag.AlignHCenter)
        card_layout.addSpacing(32)
        card_layout.addWidget(actions)
        note = self._label("网络恢复后系统会自动完成完整分析，当前无需操作。", "resultNote", alignment=Qt.AlignmentFlag.AlignCenter)
        note.setProperty("mutedText", True)
        card_layout.addSpacing(24)
        card_layout.addWidget(note)
        content_layout.addWidget(card, alignment=Qt.AlignmentFlag.AlignHCenter)
        content_layout.addStretch(1)
        layout.addWidget(content, 1)
        return page

    def _build_records_page(self) -> QWidget:
        page, layout = self._new_page(PageId.RECORDS)
        body = QWidget()
        body.setObjectName("pageCanvas")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        content = QWidget()
        content.setObjectName("recordsContent")
        content.setFixedWidth(1120)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(32, 48, 32, 40)
        content_layout.setSpacing(0)
        content_layout.addWidget(self._label("检测记录", "pageTitle"))
        subtitle = self._label("默认显示本机构最新记录，搜索仅在当前机构范围内执行。", "recordsSubtitle")
        subtitle.setProperty("secondaryText", True)
        content_layout.addSpacing(8)
        content_layout.addWidget(subtitle)
        content_layout.addSpacing(24)
        filters = QFrame()
        filters.setObjectName("recordFilters")
        filters_layout = QHBoxLayout(filters)
        filters_layout.setContentsMargins(0, 0, 0, 0)
        filters_layout.setSpacing(12)
        search = QLineEdit()
        search.setObjectName("recordSearchInput")
        search.setPlaceholderText("按机构编号 / 病历号搜索")
        search.setAccessibleName("按机构编号搜索检测记录")
        search.setFixedWidth(360)
        status = QComboBox()
        status.setObjectName("recordStatusFilter")
        status.setAccessibleName("按报告状态筛选检测记录")
        for label, value in (("报告状态：全部", ""), ("完整报告", "完整报告"), ("基础报告", "基础报告"), ("分析中", "分析中")):
            status.addItem(label, value)
        dates = QComboBox()
        dates.setObjectName("recordDateFilter")
        dates.setAccessibleName("按日期筛选检测记录")
        dates.addItem("日期：全部", "")
        dates.addItem("日期：今日", "today")
        filters_layout.addWidget(search)
        filters_layout.addWidget(status)
        filters_layout.addWidget(dates)
        filters_layout.addStretch(1)
        search_button = QPushButton("搜索")
        search_button.setObjectName("recordSearchButton")
        search_button.setAccessibleName("搜索检测记录")
        search_button.setMinimumSize(88, 44)
        filters_layout.addWidget(search_button)
        content_layout.addWidget(filters)
        content_layout.addSpacing(20)
        table = self._records_table("recordsTable")
        table.setColumnCount(5)
        table.setHorizontalHeaderLabels(("编号", "测试项目", "时间", "报告状态", ""))
        table.setFixedHeight(440)
        content_layout.addWidget(table)
        content_layout.addStretch(1)
        actions = QFrame()
        actions.setObjectName("pageActions")
        actions.setVisible(False)
        content_layout.addWidget(actions)
        body_layout.addWidget(
            content,
            1,
            alignment=Qt.AlignmentFlag.AlignHCenter,
        )
        layout.addWidget(body, 1)
        return page

    def _build_report_page(self) -> QWidget:
        page, layout = self._new_page(PageId.REPORT_PREVIEW)
        header = QFrame()
        header.setObjectName("reportHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(24, 0, 24, 0)
        back = self._action_button("BACK_TO_RECORDS", primary=False, ghost=True, label="← 检测记录")
        back.clicked.connect(lambda: self.show_page(PageId.RECORDS))
        header_layout.addWidget(back)
        header_layout.addWidget(self._label("完整分析报告", "reportPreviewTitle"))
        version = self._status_pill("reportVersionPill", "完整版 v2", "neutral")
        header_layout.addWidget(version)
        header_layout.addStretch(1)
        actions = QFrame()
        actions.setObjectName("pageActions")
        action_layout = QHBoxLayout(actions)
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.setSpacing(12)
        action_layout.addWidget(self._action_button("EXPORT_PDF", primary=False))
        action_layout.addWidget(self._action_button("PRINT_REPORT", primary=False))
        header_layout.addWidget(actions)
        layout.addWidget(header)
        meta = QFrame()
        meta.setObjectName("reportMetaBar")
        meta.setStyleSheet("background: #EFF5FC; border-bottom: 1px solid #B7D3F2;")
        meta_layout = QHBoxLayout(meta)
        meta_layout.setContentsMargins(24, 0, 24, 0)
        meta_layout.addWidget(self._label("机构编号 ＊＊2781　·　生成时间 2026-07-20 10:22　·　报告编号 R-20260720-0007", "reportPreviewMeta"))
        meta_layout.addStretch(1)
        updated = self._label("已有更新版本 v3，可切换查看", "reportUpdated")
        updated.setStyleSheet("font-size: 14px; color: #2569BC; font-weight: 600;")
        meta_layout.addWidget(updated)
        meta.setFixedHeight(44)
        layout.addWidget(meta)
        workspace = QScrollArea()
        workspace.setWidgetResizable(True)
        workspace.setFrameShape(QFrame.Shape.NoFrame)
        work = QFrame()
        work.setObjectName("reportWorkspace")
        work_layout = QVBoxLayout(work)
        work_layout.setContentsMargins(32, 32, 32, 32)
        paper = self._report_paper()
        work_layout.addWidget(paper, alignment=Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        workspace.setWidget(work)
        layout.addWidget(workspace, 1)
        return page

    def _build_support_page(self) -> QWidget:
        page, layout = self._new_page(PageId.SUPPORT)
        content = QWidget()
        content.setObjectName("pageCanvas")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(32, 64, 32, 40)
        content_layout.setSpacing(0)
        inner = QWidget()
        inner.setFixedWidth(720)
        inner_layout = QVBoxLayout(inner)
        inner_layout.setContentsMargins(0, 0, 0, 0)
        inner_layout.addWidget(self._label("设备与支持", "pageTitle"))
        subtitle = self._label("如遇持续错误，请记录错误编号后联系平台支持，串口、队列与日志细节不在此展示。", "supportSubtitle")
        subtitle.setProperty("secondaryText", True)
        subtitle.setWordWrap(True)
        inner_layout.addSpacing(8)
        inner_layout.addWidget(subtitle)
        inner_layout.addSpacing(28)
        support = QFrame()
        support.setObjectName("supportCard")
        support_layout = QVBoxLayout(support)
        support_layout.setContentsMargins(24, 8, 24, 8)
        for title, object_name, default, tone in (
            ("压力设备", "deviceHealth", "已连接", "success"),
            ("数据同步", "syncHealth", "正常", "success"),
            ("待同步数据", "pendingCount", "0 次", "neutral"),
            ("上次成功联网", "lastOnline", "2026-07-20 10:18", "neutral"),
            ("软件版本", "appVersion", "--", "neutral"),
        ):
            support_layout.addWidget(self._support_row(title, object_name, default, tone))
        inner_layout.addWidget(support)
        inner_layout.addSpacing(28)
        actions = QFrame()
        actions.setObjectName("pageActions")
        action_layout = QHBoxLayout(actions)
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.setSpacing(12)
        action_layout.addWidget(self._action_button("RECHECK_SYSTEM", primary=False))
        action_layout.addWidget(self._action_button("EXPORT_DIAGNOSTIC", primary=False, ghost=True))
        maintenance = self._action_button(
            "OPEN_ENGINEERING_MAINTENANCE", primary=False, ghost=True
        )
        maintenance.setVisible(False)
        maintenance.setToolTip("仅在已配置工程授权与设备绑定的终端可用")
        action_layout.addWidget(maintenance)
        deletion = self._action_button("OPEN_SESSION_DELETION", primary=False, ghost=True)
        deletion.setVisible(False)
        deletion.setToolTip("仅在部署明确接入单会话人工清理服务时可用")
        action_layout.addWidget(deletion)
        action_layout.addStretch(1)
        inner_layout.addWidget(actions)
        note = self._label("诊断包默认不含原始会话与身份明文；附加会话数据需要独立确认。支持热线 400-820-1120。", "supportNote")
        note.setProperty("mutedText", True)
        note.setWordWrap(True)
        inner_layout.addSpacing(24)
        inner_layout.addWidget(note)
        inner_layout.addStretch(1)
        content_layout.addWidget(inner, alignment=Qt.AlignmentFlag.AlignHCenter)
        content_layout.addStretch(1)
        layout.addWidget(content, 1)
        return page

    def _wizard_header(self, title: str, step: int | None, back_text: str = "← 返回") -> QFrame:
        header = QFrame()
        header.setObjectName("wizardHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(32, 0, 32, 0)
        back = self._action_button("BACK", primary=False, ghost=True, label=back_text)
        header_layout.addWidget(back)
        title_label = self._label(title, "wizardTitle", alignment=Qt.AlignmentFlag.AlignCenter)
        title_label.setStyleSheet("font-size: 20px; font-weight: 600;")
        header_layout.addWidget(title_label, 1)
        spacer = QWidget()
        spacer.setFixedWidth(max(80, back.sizeHint().width()))
        header_layout.addWidget(spacer)
        return header

    def _stepbar(self, current: int) -> QFrame:
        frame = QFrame()
        frame.setObjectName("wizardStepBar")
        frame.setFixedHeight(68)
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addStretch(1)
        for index, label in enumerate(_WIZARD_STEPS):
            done = index < current
            circle = QFrame()
            circle.setProperty("stepCircle", True)
            circle.setProperty("stepActive", index == current)
            circle.setProperty("stepDone", done)
            circle_layout = QHBoxLayout(circle)
            circle_layout.setContentsMargins(0, 0, 0, 0)
            if done:
                done_icon = QSvgWidget()
                done_icon.setObjectName(f"stepDoneIcon{index}")
                done_icon.setFixedSize(14, 14)
                done_icon.load(str(self._icon_asset("status-success.svg")))
                circle_layout.addWidget(done_icon)
            else:
                circle_layout.addWidget(
                    self._label(
                        str(index + 1),
                        f"stepNumber{index}",
                        alignment=Qt.AlignmentFlag.AlignCenter,
                    )
                )
            layout.addWidget(circle)
            text_label = self._label(label, f"stepLabel{index}")
            text_label.setProperty("stepLabel", True)
            text_label.setProperty("stepActive", index == current)
            text_label.setProperty("stepDone", done)
            layout.addWidget(text_label)
            if index < len(_WIZARD_STEPS) - 1:
                line = QFrame()
                line.setProperty("stepLine", True)
                line.setProperty("stepDone", index < current)
                line.setFixedWidth(64)
                layout.addWidget(line)
        layout.addStretch(1)
        return frame

    def _wizard_body(self) -> tuple[QWidget, QVBoxLayout]:
        body = QWidget()
        body.setObjectName("pageCanvas")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(32, 48, 32, 48)
        layout.setSpacing(0)
        inner = QWidget()
        inner.setFixedWidth(720)
        inner_layout = QVBoxLayout(inner)
        inner_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(inner, alignment=Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        return body, inner_layout

    def _wizard_footer(self, actions: tuple[str, ...], *, labels: dict[str, str] | None = None) -> QFrame:
        footer = QFrame()
        footer.setObjectName("pageActions")
        footer.setProperty("wizardFooter", True)
        footer.setFixedHeight(92)
        layout = QHBoxLayout(footer)
        layout.setContentsMargins(32, 18, 32, 18)
        layout.addStretch(1)
        inner = QWidget()
        inner.setFixedWidth(720)
        inner_layout = QHBoxLayout(inner)
        inner_layout.setContentsMargins(0, 0, 0, 0)
        inner_layout.setSpacing(12)
        for index, action in enumerate(actions):
            primary = index == len(actions) - 1 and action not in {"BACK", "SKIP_PROFILE", "RECHECK"}
            button = self._action_button(action, primary=primary, ghost=action in {"BACK", "SKIP_PROFILE"}, label=(labels or {}).get(action))
            if primary:
                button.setMinimumHeight(56)
            inner_layout.addWidget(button)
            if index == 0 and len(actions) > 1:
                inner_layout.addStretch(1)
        layout.addWidget(inner)
        layout.addStretch(1)
        return footer

    def _preflight_footer(self) -> QFrame:
        """Build the two-state P-05 footer without changing its geometry."""

        footer = QFrame()
        footer.setObjectName("pageActions")
        footer.setProperty("wizardFooter", True)
        footer.setFixedHeight(92)
        outer = QHBoxLayout(footer)
        outer.setContentsMargins(32, 18, 32, 18)
        outer.addStretch(1)
        inner = QWidget()
        inner.setFixedWidth(720)
        inner_layout = QHBoxLayout(inner)
        inner_layout.setContentsMargins(0, 0, 0, 0)
        left = QPushButton("重新检查")
        left.setObjectName("RECHECK")
        left.setAccessibleName("重新检查")
        left.setProperty("importance", "ghost")
        left.setMinimumHeight(48)
        left.clicked.connect(self._handle_preflight_secondary)
        right = QPushButton("进入站位引导")
        right.setObjectName("ENTER_POSITION")
        right.setAccessibleName("进入站位引导")
        right.setProperty("importance", "primary")
        right.setMinimumHeight(56)
        right.clicked.connect(self._handle_preflight_primary)
        inner_layout.addWidget(left)
        inner_layout.addStretch(1)
        inner_layout.addWidget(right)
        outer.addWidget(inner)
        outer.addStretch(1)
        return footer

    def _handle_preflight_secondary(self) -> None:
        if self._preflight_failed:
            self.show_page(PageId.CONSENT)
            return
        self._dispatch("RECHECK")

    def _handle_preflight_primary(self) -> None:
        self._dispatch(
            "ENTER_POSITION"
            if self._preflight_ready and not self._preflight_failed
            else "RECHECK"
        )

    def _records_table(self, object_name: str) -> QTableWidget:
        table = QTableWidget(0, 5)
        table.setObjectName(object_name)
        table.setAccessibleName("检测记录")
        table.setAlternatingRowColors(True)
        # The design-system DataTable uses only horizontal row separators.
        # QTableWidget draws a grid by default, which created the vertical
        # dividers the operator correctly flagged in the workbench.
        table.setShowGrid(False)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(56)
        header = table.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        # Match the source table's natural, left-aligned data columns.  The
        # status column takes the remaining width; the compact action column
        # stays at the far right instead of making all five columns equal.
        for column, width in ((0, 214), (1, 208), (2, 168), (4, 80)):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Fixed)
            table.setColumnWidth(column, width)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        # Rows are not themselves actions: the explicit “查看” control opens a
        # report.  Disabling persistent row selection prevents Qt's native
        # palette from turning dark text white on the source's pale background.
        table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        return table

    @staticmethod
    def _set_recent_table_height(table: QTableWidget, row_count: int) -> None:
        """Keep the P-01 table's fixed 300px design footprint.

        The rows are real persisted records; empty space is intentional when
        fewer than five records exist and must not collapse the workbench.
        """

        del row_count
        # 44px header + five 56px rows + the outer border.  The design source
        # labels this footprint as “300px”, but its rendered five-row example
        # has this 326px physical height; using 300 here hid the fifth row
        # behind a scrollbar.
        table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        table.setFixedHeight(44 + 5 * table.verticalHeader().defaultSectionSize() + 2)

    def _checklist_item(self, object_name: str, label: str, hint: str, tone: str) -> QFrame:
        row = QFrame()
        row.setObjectName(f"{object_name}Row")
        row.setFixedHeight(64)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        icon = QFrame()
        icon.setObjectName(f"{object_name}Pill")
        icon.setProperty("checklistIcon", True)
        icon.setProperty("checklistTone", tone)
        icon.setAccessibleName("通过" if tone == "success" else "失败")
        icon.setFixedSize(24, 24)
        icon_layout = QVBoxLayout(icon)
        icon_layout.setContentsMargins(5, 5, 5, 5)
        glyph = QSvgWidget()
        glyph.setObjectName(f"{object_name}Glyph")
        glyph.load(
            str(
                self._icon_asset(
                    "status-success.svg"
                    if tone == "success"
                    else "status-error.svg"
                )
            )
        )
        icon_layout.addWidget(glyph)
        layout.addWidget(icon)
        name = self._label(label, object_name)
        layout.addWidget(name)
        layout.addStretch(1)
        hint_label = self._label(hint, f"{object_name}Hint")
        hint_label.setProperty("secondaryText", True)
        layout.addWidget(hint_label)
        return row

    def _set_checklist_tone(
        self,
        icon: QFrame,
        tone: str,
        *,
        object_name: str,
    ) -> None:
        icon.setProperty("checklistTone", tone)
        icon.setAccessibleName("通过" if tone == "success" else "失败")
        glyph = icon.findChild(QSvgWidget, f"{object_name}Glyph")
        glyph.load(
            str(
                self._icon_asset(
                    "status-success.svg"
                    if tone == "success"
                    else "status-error.svg"
                )
            )
        )
        icon.style().unpolish(icon)
        icon.style().polish(icon)

    def _support_row(self, title: str, object_name: str, value: str, tone: str) -> QFrame:
        row = QFrame()
        row.setFixedHeight(64)
        row.setStyleSheet("border-bottom: 1px solid #E2E8F0;")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        key = self._label(title, f"{object_name}Label")
        key.setProperty("secondaryText", True)
        layout.addWidget(key)
        layout.addStretch(1)
        if tone == "success":
            layout.addWidget(self._status_pill(f"{object_name}Pill", value, tone))
        else:
            val = self._label(value, object_name)
            val.setProperty("secondaryText", True)
            layout.addWidget(val)
        if tone == "success":
            # Keep the update target separate from the pill label for live snapshots.
            value_label = row.findChild(QLabel, f"{object_name}PillText")
            value_label.setObjectName(object_name)
        return row

    def _report_paper(self) -> QFrame:
        paper = QFrame()
        paper.setObjectName("reportPaper")
        paper.setFixedWidth(566)
        paper.setMinimumHeight(780)
        layout = QVBoxLayout(paper)
        layout.setContentsMargins(44, 40, 44, 40)
        layout.setSpacing(0)
        title_row = QHBoxLayout()
        heading = QVBoxLayout()
        heading.addWidget(self._label("足底压力健康筛查报告", "reportDocumentTitle"))
        subtitle = self._label("等待报告生成", "reportDocumentSubtitle")
        subtitle.setProperty("secondaryText", True)
        heading.addSpacing(4)
        heading.addWidget(subtitle)
        title_row.addLayout(heading)
        title_row.addStretch(1)
        title_row.addWidget(self._brand_logo(24))
        layout.addLayout(title_row)
        line = QFrame()
        line.setFixedHeight(2)
        line.setStyleSheet("background: #2569BC; border: 0;")
        layout.addSpacing(16)
        layout.addWidget(line)
        metadata = self._label("有效检测完成后显示受试者编号、测试时间和报告版本", "reportDocumentMeta")
        metadata.setProperty("secondaryText", True)
        layout.addSpacing(16)
        layout.addWidget(metadata)
        layout.addSpacing(24)
        layout.addWidget(self._label("筛查摘要", "reportSectionSummary"))
        layout.itemAt(layout.count() - 1).widget().setProperty("reportSection", True)
        tags = QHBoxLayout()
        tags.addWidget(self._status_pill("reportAttention", "等待生成", "neutral"))
        tags.addWidget(self._status_pill("reportRetest", "不作预判", "info"))
        tags.addStretch(1)
        layout.addSpacing(10)
        layout.addLayout(tags)
        summary = self._label("完成有效检测后，系统将展示与该报告版本对应的基础分析摘要。未生成报告前，不显示个体风险、诊断或建议。", "reportPreviewSummary")
        summary.setWordWrap(True)
        summary.setProperty("secondaryText", True)
        layout.addSpacing(12)
        layout.addWidget(summary)
        layout.addSpacing(22)
        metrics_title = self._label("核心指标", "reportMetricsTitle")
        metrics_title.setProperty("reportSection", True)
        layout.addWidget(metrics_title)
        metrics = self._label("等待有效会话的已批准指标", "reportPreviewMetrics")
        metrics.setWordWrap(True)
        layout.addSpacing(10)
        layout.addWidget(metrics)
        layout.addSpacing(22)
        charts_title = self._label("图表", "reportChartsTitle")
        charts_title.setProperty("reportSection", True)
        layout.addWidget(charts_title)
        chart_row = QHBoxLayout()
        mini_heatmap = HeatmapWidget(physical_grid=self._physical_grid)
        mini_heatmap.setMinimumSize(230, 150)
        mini_heatmap.setMaximumHeight(150)
        chart_row.addWidget(mini_heatmap)
        placeholder = QFrame()
        placeholder.setProperty("reportPlaceholder", True)
        placeholder.setMinimumSize(230, 150)
        placeholder_layout = QVBoxLayout(placeholder)
        text = self._label("稳定性轨迹和载荷曲线\n当前基础报告不显示", "copChartPlaceholder", alignment=Qt.AlignmentFlag.AlignCenter)
        text.setProperty("mutedText", True)
        placeholder_layout.addWidget(text)
        chart_row.addWidget(placeholder)
        layout.addSpacing(10)
        layout.addLayout(chart_row)
        layout.addSpacing(22)
        params = self._label("专业参数", "reportParametersTitle")
        params.setProperty("reportSection", True)
        layout.addWidget(params)
        parameter_text = self._label("完成有效检测后，将按报告类型显示可用指标及其解释边界。", "reportParameters")
        parameter_text.setProperty("secondaryText", True)
        layout.addSpacing(10)
        layout.addWidget(parameter_text)
        layout.addStretch(1)
        footer = self._label("报告生成后将在此显示版本、生成时间和适用范围。", "reportPreviewFooter")
        footer.setWordWrap(True)
        footer.setProperty("mutedText", True)
        layout.addWidget(footer)
        return paper

    @staticmethod
    def _label(text: str, object_name: str, *, alignment: Qt.AlignmentFlag | None = None) -> QLabel:
        label = QLabel(text)
        label.setObjectName(object_name)
        if alignment is not None:
            label.setAlignment(alignment)
        return label

    @staticmethod
    def _divider_with_text(text: str) -> QWidget:
        host = QWidget()
        layout = QHBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        line_left = QFrame()
        line_left.setFrameShape(QFrame.Shape.HLine)
        line_right = QFrame()
        line_right.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(line_left, 1)
        middle = QLabel(text)
        middle.setProperty("mutedText", True)
        layout.addWidget(middle)
        layout.addWidget(line_right, 1)
        return host

    def _profile_combo(self, object_name: str, accessible_name: str, values: tuple[tuple[str, str | None], ...]) -> QComboBox:
        combo = QComboBox()
        combo.setObjectName(object_name)
        combo.setAccessibleName(accessible_name)
        for label, value in values:
            combo.addItem(label, value)
        return combo

    def _field_with_unit(self, object_name: str, label: str, unit: str, value: str) -> QWidget:
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        label_widget = self._label(label, f"{object_name}Label")
        label_widget.setProperty("fieldLabel", True)
        layout.addWidget(label_widget)
        row = QHBoxLayout()
        input_field = QLineEdit(value)
        input_field.setObjectName(object_name)
        input_field.setAccessibleName(f"{label}{unit}（选填）")
        row.addWidget(input_field)
        unit_label = self._label(unit, f"{object_name}Unit")
        unit_label.setProperty("secondaryText", True)
        row.addWidget(unit_label)
        layout.addLayout(row)
        return host

    def _field_group(self, label: str, widget: QWidget) -> QWidget:
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        label_widget = self._label(label, f"{widget.objectName()}Label")
        label_widget.setProperty("fieldLabel", True)
        layout.addWidget(label_widget)
        layout.addWidget(widget)
        return host

    def _hidden_profile_controls(self) -> QWidget:
        hidden = QWidget()
        hidden.setVisible(False)
        layout = QVBoxLayout(hidden)
        for field_name in ("ageBand", "sex", "height", "weight", "conditionTags", "injuryTags"):
            layout.addWidget(self._field_state_combo(f"{field_name}State", f"{field_name} 提供状态"))
        condition = QLineEdit()
        condition.setObjectName("conditionTagsInput")
        injury = QLineEdit()
        injury.setObjectName("injuryTagsInput")
        layout.addWidget(condition)
        layout.addWidget(injury)
        return hidden

    @staticmethod
    def _field_state_combo(object_name: str, accessible_name: str) -> QComboBox:
        selector = QComboBox()
        selector.setObjectName(object_name)
        selector.setAccessibleName(accessible_name)
        for label, value in (("已填写", "PROVIDED"), ("明确无", "NONE_REPORTED"), ("未知/未询问", "UNKNOWN"), ("拒绝提供", "DECLINED"), ("不适用", "NOT_APPLICABLE")):
            selector.addItem(label, value)
        selector.setCurrentIndex(2)
        return selector

    def _action_button(self, action: str, *, primary: bool, ghost: bool = False, label: str | None = None) -> QPushButton:
        button = QPushButton(label or _ACTION_LABELS.get(action, action))
        button.setObjectName(action)
        button.setAccessibleName(button.text())
        button.setMinimumHeight(48)
        if action == "STOP_SCREENING":
            button.setProperty("importance", "danger")
        elif ghost:
            button.setProperty("importance", "ghost")
        else:
            button.setProperty("importance", "primary" if primary else "secondary")
        if action == "STOP_SCREENING":
            button.clicked.connect(self._show_stop_confirmation)
        elif action not in {"BACK", "BACK_TO_RECORDS", "VIEW_POLICY", "ENTER_POSITION"}:
            button.clicked.connect(lambda: self._dispatch(action))
        return button

    def _dispatch(self, action: str) -> None:
        if self._on_action is not None:
            self._on_action(action)

    def _show_stop_confirmation(self) -> None:
        """Show the source P-07 blocking confirmation over the live screen."""
        page = self._pages[PageId.ACQUIRING]
        overlay = page.findChild(QFrame, "stopConfirmationOverlay")
        self._stop_confirmation_pending = True
        overlay.setGeometry(page.rect())
        overlay.show()
        overlay.raise_()
        page.findChild(QPushButton, "CONTINUE_SCREENING").setFocus()

    def _confirm_stop_screening(self) -> None:
        self._reset_stop_confirmation()
        self._dispatch("STOP_SCREENING")

    def _reset_stop_confirmation(self) -> None:
        self._stop_confirmation_pending = False
        page = self._pages.get(PageId.ACQUIRING)
        if page is None:
            return
        overlay = page.findChild(QFrame, "stopConfirmationOverlay")
        if overlay is not None:
            overlay.hide()

    def _present_result_state(self, state: WorkflowState) -> None:
        page = self._pages[PageId.RESULT]
        report_ready = state.report_status is ReportStatus.BASIC_READY
        retry_required = state.validity in {SessionValidity.INVALID, SessionValidity.INCOMPLETE, SessionValidity.FAILED}
        retry_allowed = (
            retry_required
            and (
                state.error is None
                or state.error.action is ClientAction.RETRY_SCREENING
            )
        )
        page.findChild(QPushButton, "VIEW_BASIC_REPORT").setVisible(report_ready)
        page.findChild(QPushButton, "START_NEXT_SCREENING").setVisible(report_ready)
        page.findChild(QPushButton, "RETURN_WORKBENCH").setVisible(retry_required)
        page.findChild(QPushButton, "RETRY_SCREENING").setVisible(retry_allowed)
        title = page.findChild(QLabel, "resultTitle")
        summary = page.findChild(QLabel, "resultSummary")
        basic = page.findChild(QLabel, "basicReportStatusText")
        basic_pill = page.findChild(QFrame, "basicReportStatus")
        full = page.findChild(QFrame, "fullReportStatus")
        note = page.findChild(QLabel, "resultNote")
        if report_ready:
            page.findChild(QFrame, "resultStatusIcon").setStyleSheet(
                "background: #EBF7F0; border: 1px solid #BFE5D0; border-radius: 36px;"
            )
            page.findChild(QSvgWidget, "resultSuccessIcon").load(
                str(self._icon_asset("status-success.svg"))
            )
            title.setText("基础报告已生成")
            summary.setText("本次足底压力筛查已完成质量校核，基础报告可立即查看。")
            basic.setText(f"基础报告已生成（版本 {state.report_version}）")
            basic_pill.hide()
            full.show()
            note.show()
        elif retry_required:
            page.findChild(QFrame, "resultStatusIcon").setStyleSheet(
                "background: #FDF6E6; border: 1px solid #F2DFAE; border-radius: 36px;"
            )
            page.findChild(QSvgWidget, "resultSuccessIcon").load(
                str(self._icon_asset("status-warning.svg"))
            )
            title.setText("本次检测未完成")
            summary.setText(
                state.error.operator_message
                if state.error is not None
                else "本次采集未通过质量校核，未生成报告。请协助受试者重新站稳后再次检测。"
            )
            basic.setText("本次检测未完成")
            self._set_pill_tone(basic_pill, "warning")
            basic_pill.show()
            full.hide()
            note.hide()
        else:
            title.setText("正在完成本地处理")
            summary.setText("正在生成基础报告，请稍候。")
            basic.setText("本地处理中")
            self._set_pill_tone(basic_pill, "info")
            basic_pill.show()
            full.hide()
            note.hide()

    def _present_preflight_state(self, state: WorkflowState) -> None:
        page = self._pages[PageId.PREFLIGHT]
        failed = state.error is not None
        self._preflight_failed = failed
        self._preflight_ready = state.preflight_ready
        instruction = page.findChild(QLabel, "preflightInstruction")
        note = page.findChild(QLabel, "preflightNote")
        left = page.findChild(QPushButton, "RECHECK")
        right = page.findChild(QPushButton, "ENTER_POSITION")
        check_targets = {
            "device_connected": ("deviceCheck", "回放数据源已就绪"),
            "fixture_replay": ("deviceCheck", "回放数据源已就绪"),
            "storage_space": ("storageCheck", "空间充足"),
            "calibration_status": (
                "calibrationCheck",
                "回放模式，不适用",
            ),
            "data_sync": ("syncCheck", "本地调试，无需云端同步"),
            "network_gate": ("syncCheck", "联网与待传门槛允许新检测"),
            "zero_load": ("zeroLoadCheck", "五秒空载检查已通过"),
        }
        default_targets = (
            ("deviceCheck", "等待检查"),
            ("storageCheck", "等待检查"),
            ("calibrationCheck", "等待检查"),
            ("syncCheck", "等待检查"),
            ("zeroLoadCheck", "等待检查"),
        )
        if not state.preflight_checks:
            for object_name, text in default_targets:
                page.findChild(QLabel, f"{object_name}Hint").setText(text)
        for check in state.preflight_checks:
            object_name, ready_text = check_targets.get(
                check.key,
                ("syncCheck", "检查通过"),
            )
            hint = page.findChild(QLabel, f"{object_name}Hint")
            pill = page.findChild(QFrame, f"{object_name}Pill")
            hint.setText(
                check.operator_message
                or (ready_text if check.ready else "检查未通过")
            )
            hint.setStyleSheet("" if check.ready else "color: #C23B3B;")
            self._set_checklist_tone(
                pill,
                "success" if check.ready else "danger",
                object_name=object_name,
            )
        if failed:
            instruction.setText("请处理上述提示后重新检查")
            note.hide()
            left.setText("← 返回")
            left.setAccessibleName("返回授权确认")
            right.setText("重新检查")
            right.setAccessibleName("重新检查")
            right.setEnabled(True)
        else:
            instruction.setText("请确保压力垫上暂时无人站立")
            note.setText(
                "五项预检已通过，请点击进入站位引导"
                if state.preflight_ready
                else "正在执行本次设备预检"
            )
            note.show()
            left.setText("重新检查")
            left.setAccessibleName("重新检查")
            right.setText("进入站位引导")
            right.setAccessibleName("进入站位引导")
            right.setEnabled(state.preflight_ready)

    @staticmethod
    def _icon_asset(name: str) -> Path:
        return Path(__file__).resolve().parent / "assets" / name
