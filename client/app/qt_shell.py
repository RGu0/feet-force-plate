from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtSvgWidgets import QSvgWidget
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
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
from client.reporting.models import BasicReportDocument
from client.workflow.models import ReportStatus, SessionValidity, WorkflowState

from .design_system import apply_design_system
from .heatmap import HeatmapWidget
from .pages import PAGE_DEFINITIONS, PageId, page_for_step
from .position_guide import FootPlacementWidget
from .ui_models import DashboardSnapshot, ScreeningRecordRow, SupportSnapshot


_ACTION_LABELS = {
    "START_NEW_SCREENING": "开始新的检测",
    "CONFIRM_SUBJECT": "确认并继续",
    "CREATE_ANONYMOUS_SUBJECT": "无机构编号，快速建档",
    "SAVE_PROFILE": "保存并继续",
    "SKIP_PROFILE": "跳过",
    "CONFIRM_CONSENT": "同意并继续",
    "RECHECK": "重新检查",
    "START_ACQUISITION": "手动开始",
    "STOP_SCREENING": "停止检测",
    "VIEW_BASIC_REPORT": "查看基础报告",
    "START_NEXT_SCREENING": "开始下一位检测",
    "RETRY_SCREENING": "重新检测",
    "VIEW_SELECTED_REPORT": "查看报告",
    "EXPORT_PDF": "导出 PDF",
    "PRINT_REPORT": "打印",
    "RECHECK_SYSTEM": "重新检查",
    "EXPORT_DIAGNOSTIC": "导出问题诊断包",
}

_WIZARD_STEPS = ("受试者", "选填信息", "授权确认", "设备预检", "站位引导")
_TOPBAR_PAGES = {PageId.WORKBENCH, PageId.RESULT, PageId.RECORDS, PageId.SUPPORT}


class ScreeningWindow(QMainWindow):
    """Operator desktop shell faithfully composed from the Steady Health kit."""

    def __init__(self, *, on_action: Callable[[str], None] | None = None) -> None:
        super().__init__()
        self.setObjectName("screeningWindow")
        self.setWindowTitle("FeetForcePlate 足底压力健康筛查")
        self.setMinimumSize(1280, 720)
        self._on_action = on_action
        self._stop_confirmation_pending = False
        self._record_rows: tuple[ScreeningRecordRow, ...] = ()
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
            page.findChild(QLabel, "positionStatus").setText(
                state.position_guidance.instruction_text
            )
            page.findChild(QLabel, "countdownLabel").setText(
                state.position_guidance.countdown_text
            )
        if state.acquisition_instruction is not None:
            page = self._pages[PageId.ACQUIRING]
            page.findChild(QLabel, "acquisitionInstruction").setText(
                state.acquisition_instruction
            )
            page.findChild(QLabel, "acquisitionStatus").setText("正在采集")
        if state.remaining_seconds is not None:
            minutes, seconds = divmod(state.remaining_seconds, 60)
            page = self._pages[PageId.ACQUIRING]
            page.findChild(QLabel, "remainingTime").setText(
                f"剩余 {minutes:02d}:{seconds:02d}"
            )
            page.findChild(QLabel, "remainingSeconds").setText(str(state.remaining_seconds))
            page.findChild(QProgressBar, "acquisitionProgress").setValue(
                max(0, min(100, int((1 - state.remaining_seconds / 30) * 100)))
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
        page.findChild(QLabel, "subjectMatchSummary").setText(message)
        conflict = page.findChild(QFrame, "subjectConflictView")
        match = page.findChild(QFrame, "matchCard")
        is_conflict = "多个" in message or "不能自动" in message
        conflict.setVisible(is_conflict)
        match.setVisible(not is_conflict)

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
        page.findChild(QLabel, "pendingCount").setText(snapshot.pending_summary)
        page.findChild(QLabel, "appVersion").setText(snapshot.app_version)

    def present_report_document(self, document: BasicReportDocument) -> None:
        page = self._pages[PageId.REPORT_PREVIEW]
        page.findChild(QLabel, "reportPreviewTitle").setText(
            f"完整分析报告 v{document.version}"
        )
        page.findChild(QLabel, "reportPreviewMeta").setText(
            f"受试者编号　{document.subject_display_id}　·　测试时间　{document.captured_at:%Y-%m-%d %H:%M}"
        )
        page.findChild(QLabel, "reportPreviewSummary").setText(document.summary)
        page.findChild(QLabel, "reportPreviewMetrics").setText(
            " · ".join(
                f"{metric.label} {metric.value:.1f}{'%' if metric.unit == 'percent' else metric.unit}"
                for metric in document.metrics
            )
        )
        page.findChild(QLabel, "reportPreviewFooter").setText(
            f"报告编号 {document.report_id} · 完整 v{document.version} · 生成 {document.generated_at:%Y-%m-%d %H:%M} · {document.disclaimer}"
        )

    def _present_banners(self, state: WorkflowState) -> None:
        if state.notice is None:
            self._notice_banner.hide()
        else:
            self._notice_banner.setText(state.notice)
            self._notice_banner.show()
        if state.error is None:
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
        content.setFixedWidth(1120)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(32, 0, 32, 40)
        content_layout.setSpacing(0)
        hero = QWidget()
        hero.setObjectName("workbenchHero")
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(0, 144, 0, 64)
        hero_layout.setSpacing(0)
        title = self._label("足底压力健康筛查", "pageTitle", alignment=Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 32px;")
        subtitle = self._label("请引导受试者到达压力垫前，准备就绪后开始新的检测。", "pageSubtitle", alignment=Qt.AlignmentFlag.AlignCenter)
        start = self._action_button("START_NEW_SCREENING", primary=True)
        start.setMinimumSize(220, 64)
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
        recent.setFixedHeight(330)
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
        summary = self._label("编号 ＊＊2781\n年龄 64 岁　性别 女　上次检测 07-12", "subjectMatchSummary")
        summary.setStyleSheet("font-size: 20px; font-weight: 600;")
        summary.setWordWrap(True)
        summary.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        note = self._label("请核对是否为本人，避免同名或错号档案；如信息不符请返回重新查找。", "matchNote")
        note.setProperty("secondaryText", True)
        note.setWordWrap(True)
        note.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        text_column.addWidget(found)
        text_column.addSpacing(6)
        text_column.addWidget(summary)
        text_column.addSpacing(12)
        text_column.addWidget(note)
        match_layout.addLayout(text_column, 1)
        match_layout.addSpacing(24)
        confirm = self._action_button("CONFIRM_SUBJECT", primary=True)
        confirm.setMinimumSize(200, 56)
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
        conflict_heading = self._label("发现多个匹配档案", "conflictHeading")
        conflict_heading.setStyleSheet("font-size: 20px; font-weight: 600; color: #96600D;")
        conflict_note = self._label("系统不会自动合并，请人工确认对应受试者后再继续。", "conflictNote")
        conflict_note.setProperty("secondaryText", True)
        conflict_layout.addWidget(conflict_heading)
        conflict_layout.addWidget(conflict_note)
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
        body_layout.addWidget(self._label("基础信息（选填，可直接继续）", "pageTitle"))
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
        chips = QHBoxLayout()
        chips.setSpacing(8)
        for label in ("糖尿病", "足部不适", "平衡风险", "未提供"):
            chip = QPushButton(label)
            chip.setCheckable(True)
            chip.setMinimumHeight(36)
            chip.setProperty("importance", "secondary")
            chips.addWidget(chip)
        chips.addStretch(1)
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
        body_layout.addWidget(self._label("数据使用说明", "pageTitle"))
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
            ("calibrationCheck", "标定状态", "最近校准 07-20"),
            ("syncCheck", "数据同步", "已同步"),
        ):
            checks.addWidget(self._checklist_item(object_name, label, hint, "success"))
        body_layout.addWidget(checklist)
        instruction = self._label("请确保压力垫上暂时无人站立", "preflightInstruction", alignment=Qt.AlignmentFlag.AlignCenter)
        instruction.setProperty("secondaryText", True)
        note = self._label("全部通过后将自动进入站位引导", "preflightNote", alignment=Qt.AlignmentFlag.AlignCenter)
        note.setProperty("mutedText", True)
        body_layout.addSpacing(32)
        body_layout.addWidget(instruction)
        body_layout.addSpacing(8)
        body_layout.addWidget(note)
        body_layout.addStretch(1)
        layout.addWidget(body, 1)
        footer = self._wizard_footer(("RECHECK", "ENTER_POSITION"), labels={"ENTER_POSITION": "进入站位引导"})
        footer.findChild(QPushButton, "ENTER_POSITION").clicked.connect(lambda: self._dispatch("RECHECK"))
        layout.addWidget(footer)
        return page

    def _build_position_page(self) -> QWidget:
        page, layout = self._new_page(PageId.POSITION_GUIDANCE)
        layout.addWidget(self._wizard_header("站位引导", None, "← 取消"))
        body = QWidget()
        body.setObjectName("pageCanvas")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(32, 32, 32, 32)
        body_layout.setSpacing(0)
        body_layout.addStretch(3)
        title = self._label("请站到压力垫中央", "pageTitle", alignment=Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 40px;")
        title.setFixedHeight(48)
        subtitle = self._label("双脚自然站立，保持身体放松，目视前方", "pageSubtitle", alignment=Qt.AlignmentFlag.AlignCenter)
        subtitle.setFixedHeight(28)
        body_layout.addWidget(title)
        body_layout.addSpacing(8)
        body_layout.addWidget(subtitle)
        body_layout.addSpacing(32)
        guide = FootPlacementWidget()
        body_layout.addWidget(guide, alignment=Qt.AlignmentFlag.AlignHCenter)
        details_host = QWidget()
        details_host.setFixedWidth(360)
        details = QHBoxLayout(details_host)
        details.setContentsMargins(0, 0, 0, 0)
        details.setSpacing(24)
        status_column = QVBoxLayout()
        status_column.setContentsMargins(0, 0, 0, 0)
        status = self._label("检测到稳定站位后将自动开始", "positionStatus")
        status.setProperty("secondaryText", True)
        count_line = QHBoxLayout()
        count_line.addWidget(self._label("稳定中…", "positionState"))
        countdown = self._label("3", "countdownLabel")
        countdown.setStyleSheet("font-size: 48px; font-weight: 700; color: #2569BC;")
        count_line.addWidget(countdown)
        count_line.addStretch(1)
        status_column.addWidget(status)
        status_column.addSpacing(4)
        status_column.addLayout(count_line)
        status_host = QWidget()
        status_host.setFixedWidth(185)
        status_host.setLayout(status_column)
        details.addWidget(status_host)
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.VLine)
        separator.setStyleSheet("color: #E2E8F0;")
        separator.setFixedHeight(48)
        details.addWidget(separator)
        manual = self._action_button("START_ACQUISITION", primary=True)
        manual.setMinimumSize(130, 56)
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
        heatmap = HeatmapWidget()
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
        for widget, spacing in ((status, 8), (instruction, 32), (seconds, 8), (seconds_caption, 32), (progress, 8), (note, 0)):
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
        card.setMaximumWidth(560)
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
        retry_button = self._action_button("RETRY_SCREENING", primary=True)
        action_layout.addStretch(1)
        action_layout.addWidget(next_button)
        action_layout.addWidget(view_button)
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
        content = QWidget()
        content.setObjectName("pageCanvas")
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
        search.setMinimumWidth(360)
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
        search_button.setMinimumSize(88, 44)
        filters_layout.addWidget(search_button)
        content_layout.addWidget(filters)
        content_layout.addSpacing(20)
        table = self._records_table("recordsTable")
        table.setColumnCount(5)
        table.setHorizontalHeaderLabels(("编号", "测试项目", "时间", "报告状态", ""))
        content_layout.addWidget(table, 1)
        actions = QFrame()
        actions.setObjectName("pageActions")
        actions.setVisible(False)
        content_layout.addWidget(actions)
        layout.addWidget(content, 1)
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
            ("待同步数据", "pendingCount", "待同步数据：0 次", "neutral"),
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
        frame.setFixedHeight(60)
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addStretch(1)
        for index, label in enumerate(_WIZARD_STEPS):
            circle = QFrame()
            circle.setProperty("stepCircle", True)
            circle.setProperty("stepActive", index == current)
            circle_layout = QHBoxLayout(circle)
            circle_layout.setContentsMargins(0, 0, 0, 0)
            circle_layout.addWidget(self._label(str(index + 1), f"stepNumber{index}", alignment=Qt.AlignmentFlag.AlignCenter))
            layout.addWidget(circle)
            text_label = self._label(label, f"stepLabel{index}")
            text_label.setProperty("stepLabel", True)
            text_label.setProperty("stepActive", index == current)
            layout.addWidget(text_label)
            if index < len(_WIZARD_STEPS) - 1:
                line = QFrame()
                line.setProperty("stepLine", True)
                line.setFixedWidth(64)
                layout.addWidget(line)
        layout.addStretch(1)
        return frame

    def _wizard_body(self) -> tuple[QWidget, QVBoxLayout]:
        body = QWidget()
        body.setObjectName("pageCanvas")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(32, 24, 32, 24)
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
        footer.setFixedHeight(88)
        layout = QHBoxLayout(footer)
        layout.setContentsMargins(32, 12, 32, 12)
        layout.addStretch(1)
        for index, action in enumerate(actions):
            primary = index == len(actions) - 1 and action not in {"BACK", "SKIP_PROFILE", "RECHECK"}
            button = self._action_button(action, primary=primary, ghost=action in {"BACK", "SKIP_PROFILE"}, label=(labels or {}).get(action))
            if primary:
                button.setMinimumHeight(56)
            layout.addWidget(button)
        return footer

    def _records_table(self, object_name: str) -> QTableWidget:
        table = QTableWidget(0, 5)
        table.setObjectName(object_name)
        table.setAccessibleName("检测记录")
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(56)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        return table

    def _checklist_item(self, object_name: str, label: str, hint: str, tone: str) -> QFrame:
        row = QFrame()
        row.setObjectName(f"{object_name}Row")
        row.setFixedHeight(64)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        pill = self._status_pill(f"{object_name}Pill", "", tone)
        pill.setFixedSize(24, 24)
        layout.addWidget(pill)
        name = self._label(label, object_name)
        name.setFixedWidth(150)
        layout.addWidget(name)
        hint_label = self._label(hint, f"{object_name}Hint")
        hint_label.setProperty("secondaryText", True)
        layout.addWidget(hint_label)
        layout.addStretch(1)
        return row

    def _support_row(self, title: str, object_name: str, value: str, tone: str) -> QFrame:
        row = QFrame()
        row.setFixedHeight(56)
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
        subtitle = self._label("康健社区健康服务中心 · 完整分析版", "reportDocumentSubtitle")
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
        metadata = self._label("受试者编号　＊＊2781　　　 测试时间　2026-07-20 10:20\n测试项目　静态筛查　　　　 报告版本　完整 v2", "reportDocumentMeta")
        metadata.setProperty("secondaryText", True)
        layout.addSpacing(16)
        layout.addWidget(metadata)
        layout.addSpacing(24)
        layout.addWidget(self._label("筛查摘要", "reportSectionSummary"))
        layout.itemAt(layout.count() - 1).widget().setProperty("reportSection", True)
        tags = QHBoxLayout()
        tags.addWidget(self._status_pill("reportAttention", "建议关注", "warning"))
        tags.addWidget(self._status_pill("reportRetest", "建议复测", "info"))
        tags.addStretch(1)
        layout.addSpacing(10)
        layout.addLayout(tags)
        summary = self._label("本次筛查数据已完成质量校核。建议结合日常活动情况持续关注足底受力变化，并在需要时复测。", "reportPreviewSummary")
        summary.setWordWrap(True)
        summary.setProperty("secondaryText", True)
        layout.addSpacing(12)
        layout.addWidget(summary)
        layout.addSpacing(22)
        metrics_title = self._label("核心指标", "reportMetricsTitle")
        metrics_title.setProperty("reportSection", True)
        layout.addWidget(metrics_title)
        metrics = self._label("左侧相对负重 51.2% · 右侧相对负重 48.8%", "reportPreviewMetrics")
        metrics.setWordWrap(True)
        layout.addSpacing(10)
        layout.addWidget(metrics)
        layout.addSpacing(22)
        charts_title = self._label("图表", "reportChartsTitle")
        charts_title.setProperty("reportSection", True)
        layout.addWidget(charts_title)
        chart_row = QHBoxLayout()
        mini_heatmap = HeatmapWidget()
        mini_heatmap.setMinimumSize(230, 150)
        mini_heatmap.setMaximumHeight(150)
        chart_row.addWidget(mini_heatmap)
        placeholder = QFrame()
        placeholder.setProperty("reportPlaceholder", True)
        placeholder.setMinimumSize(230, 150)
        placeholder_layout = QVBoxLayout(placeholder)
        text = self._label("COP 轨迹 / 载荷曲线\n（图表占位）", "copChartPlaceholder", alignment=Qt.AlignmentFlag.AlignCenter)
        text.setProperty("mutedText", True)
        placeholder_layout.addWidget(text)
        chart_row.addWidget(placeholder)
        layout.addSpacing(10)
        layout.addLayout(chart_row)
        layout.addSpacing(22)
        params = self._label("专业参数", "reportParametersTitle")
        params.setProperty("reportSection", True)
        layout.addWidget(params)
        parameter_text = self._label("更多专业参数将在完整分析报告中按协议版本呈现。", "reportParameters")
        parameter_text.setProperty("secondaryText", True)
        layout.addSpacing(10)
        layout.addWidget(parameter_text)
        layout.addStretch(1)
        footer = self._label("报告编号 R-20260720-0007 · 完整 v2 · 生成 2026-07-20 10:22 · 本报告为健康筛查与分析，非临床诊断。", "reportPreviewFooter")
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
        layout.addWidget(self._label(label, f"{object_name}Label"))
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
        layout.addWidget(self._label(label, f"{widget.objectName()}Label"))
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
        """Use the product's deliberately brief, in-flow dangerous confirmation."""
        stop = self._pages[PageId.ACQUIRING].findChild(
            QPushButton, "STOP_SCREENING"
        )
        if not self._stop_confirmation_pending:
            self._stop_confirmation_pending = True
            stop.setText("再次点击确认停止")
            stop.setAccessibleName("再次点击确认停止检测")
            return
        self._reset_stop_confirmation()
        self._dispatch("STOP_SCREENING")

    def _reset_stop_confirmation(self) -> None:
        self._stop_confirmation_pending = False
        page = self._pages.get(PageId.ACQUIRING)
        if page is None:
            return
        stop = page.findChild(QPushButton, "STOP_SCREENING")
        if stop is not None:
            stop.setText(_ACTION_LABELS["STOP_SCREENING"])
            stop.setAccessibleName(_ACTION_LABELS["STOP_SCREENING"])

    def _present_result_state(self, state: WorkflowState) -> None:
        page = self._pages[PageId.RESULT]
        report_ready = state.report_status is ReportStatus.BASIC_READY
        retry_required = state.validity in {SessionValidity.INVALID, SessionValidity.INCOMPLETE, SessionValidity.FAILED}
        page.findChild(QPushButton, "VIEW_BASIC_REPORT").setVisible(report_ready)
        page.findChild(QPushButton, "START_NEXT_SCREENING").setVisible(report_ready)
        page.findChild(QPushButton, "RETRY_SCREENING").setVisible(retry_required)
        title = page.findChild(QLabel, "resultTitle")
        summary = page.findChild(QLabel, "resultSummary")
        basic = page.findChild(QLabel, "basicReportStatusText")
        full = page.findChild(QFrame, "fullReportStatus")
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
            page.findChild(QFrame, "basicReportStatus").hide()
            full.show()
        elif retry_required:
            page.findChild(QFrame, "resultStatusIcon").setStyleSheet(
                "background: #FDF6E6; border: 1px solid #F2DFAE; border-radius: 36px;"
            )
            page.findChild(QSvgWidget, "resultSuccessIcon").load(
                str(self._icon_asset("status-warning.svg"))
            )
            title.setText("本次检测未完成")
            summary.setText("本次采集未通过质量校核，未生成报告。请协助受试者重新站稳后再次检测。")
            basic.setText("质量校核未通过")
            page.findChild(QFrame, "basicReportStatus").show()
            full.hide()
        else:
            title.setText("正在完成本地处理")
            summary.setText("正在生成基础报告，请稍候。")
            basic.setText("本地处理中")
            page.findChild(QFrame, "basicReportStatus").show()
            full.hide()

    def _present_preflight_state(self, state: WorkflowState) -> None:
        page = self._pages[PageId.PREFLIGHT]
        failed = state.error is not None
        hint = page.findChild(QLabel, "syncCheckHint")
        pill = page.findChild(QFrame, "syncCheckPill")
        instruction = page.findChild(QLabel, "preflightInstruction")
        note = page.findChild(QLabel, "preflightNote")
        if failed:
            hint.setText(f"{state.error.operator_message}（{state.error.code}）")
            self._set_pill_tone(pill, "danger")
            instruction.setText("请处理上述提示后重新检查")
            note.hide()
        else:
            hint.setText("已同步")
            self._set_pill_tone(pill, "success")
            instruction.setText("请确保压力垫上暂时无人站立")
            note.setText("全部通过后将自动进入站位引导")
            note.show()

    @staticmethod
    def _icon_asset(name: str) -> Path:
        return Path(__file__).resolve().parent / "assets" / name
