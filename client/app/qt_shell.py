from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from client.workflow.models import ReportStatus, SessionValidity, WorkflowState

from .pages import PAGE_DEFINITIONS, PageId, page_for_step


_ACTION_LABELS = {
    "START_NEW_SCREENING": "开始新的检测",
    "CONFIRM_SUBJECT": "确认并继续",
    "CREATE_ANONYMOUS_SUBJECT": "无机构编号，快速建档",
    "SAVE_PROFILE": "保存并继续",
    "SKIP_PROFILE": "跳过",
    "CONFIRM_CONSENT": "同意并继续",
    "RECHECK": "重新检查",
    "START_ACQUISITION": "开始检测",
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


class ScreeningWindow(QMainWindow):
    """Thin Qt shell; workflow decisions remain in the coordinator."""

    def __init__(
        self,
        *,
        on_action: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__()
        self.setWindowTitle("FeetForcePlate 足底压力健康筛查")
        self.setMinimumSize(1280, 720)
        self._on_action = on_action
        self._stop_confirmation_pending = False
        self._pages: dict[PageId, QWidget] = {}
        self._stack = QStackedWidget()
        self._notice_banner = QLabel()
        self._notice_banner.setObjectName("noticeBanner")
        self._notice_banner.setWordWrap(True)
        self._notice_banner.hide()
        self._error_banner = QLabel()
        self._error_banner.setObjectName("errorBanner")
        self._error_banner.setWordWrap(True)
        self._error_banner.hide()
        self._navigation = self._build_navigation()

        for page_id, definition in PAGE_DEFINITIONS.items():
            page = self._build_page(page_id)
            self._pages[page_id] = page
            self._stack.addWidget(page)

        content = QWidget()
        body = QHBoxLayout(content)
        body.setContentsMargins(24, 24, 24, 24)
        body.setSpacing(24)
        body.addWidget(self._navigation)

        main_column = QVBoxLayout()
        main_column.setSpacing(16)
        main_column.addWidget(self._notice_banner)
        main_column.addWidget(self._error_banner)
        main_column.addWidget(self._stack, 1)
        body.addLayout(main_column, 1)
        self.setCentralWidget(content)
        self.show_page(PageId.WORKBENCH)
        self.setStyleSheet(
            """
            QWidget { font-size: 16px; }
            QLabel#pageTitle { font-size: 28px; font-weight: 700; }
            QPushButton { min-height: 48px; padding: 0 20px; }
            QPushButton[importance="primary"] { font-weight: 700; }
            QLabel#errorBanner {
                background: #fff4e5;
                border: 1px solid #8a4b08;
                border-radius: 6px;
                color: #4a2a08;
                padding: 12px;
            }
            QLabel#noticeBanner {
                background: #e8f1ff;
                border: 1px solid #1d4ed8;
                border-radius: 6px;
                color: #172554;
                padding: 12px;
            }
            """
        )

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

    def present_state(self, state: WorkflowState) -> None:
        page_id = page_for_step(state.step)
        self.show_page(page_id)
        self._navigation.setEnabled(
            PAGE_DEFINITIONS[page_id].global_navigation_enabled
        )
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
            acquisition_page = self._pages[PageId.ACQUIRING]
            acquisition_page.findChild(
                QLabel,
                "acquisitionInstruction",
            ).setText(state.acquisition_instruction)
            acquisition_page.findChild(QLabel, "acquisitionStatus").setText(
                "当前状态：采集中"
            )
        if state.remaining_seconds is not None:
            minutes, seconds = divmod(state.remaining_seconds, 60)
            self._pages[PageId.ACQUIRING].findChild(
                QLabel,
                "remainingTime",
            ).setText(f"剩余 {minutes:02d}:{seconds:02d}")
        if page_id is PageId.RESULT:
            self._present_result_state(state)
        if state.notice is None:
            self._notice_banner.clear()
            self._notice_banner.hide()
        else:
            self._notice_banner.setText(state.notice)
            self._notice_banner.show()
        if state.error is None:
            self._error_banner.clear()
            self._error_banner.hide()
            return
        self._error_banner.setText(
            f"{state.error.operator_message}（错误编号：{state.error.code}）"
        )
        self._error_banner.show()

    def show_form_error(self, message: str) -> None:
        self._error_banner.setText(message)
        self._error_banner.show()

    def set_subject_match_summary(self, message: str) -> None:
        label = self._pages[PageId.SUBJECT_IDENTIFICATION].findChild(
            QLabel,
            "subjectMatchSummary",
        )
        label.setText(message)

    def subject_identifier(self) -> tuple[str, str]:
        page = self._pages[PageId.SUBJECT_IDENTIFICATION]
        id_type = page.findChild(QComboBox, "subjectIdTypeInput")
        external_id = page.findChild(QLineEdit, "subjectExternalIdInput")
        return str(id_type.currentData()), external_id.text()

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
                raw_value = value_widget.currentData()
                value = "" if raw_value is None else str(raw_value)
            elif isinstance(value_widget, QLineEdit):
                value = value_widget.text()
            else:
                raise RuntimeError(f"missing profile input: {field_name}")
            values[field_name] = (str(state.currentData()), value)
        return values

    def consent_choices(self) -> tuple[bool, bool]:
        page = self._pages[PageId.CONSENT]
        required = page.findChild(QCheckBox, "requiredConsent")
        research = page.findChild(QCheckBox, "researchConsent")
        return required.isChecked(), research.isChecked()

    def _build_navigation(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("globalNavigation")
        frame.setFixedWidth(190)
        layout = QVBoxLayout(frame)
        for page_id, label in (
            (PageId.WORKBENCH, "工作台"),
            (PageId.RECORDS, "检测记录"),
            (PageId.SUPPORT, "设备与支持"),
        ):
            button = QPushButton(label)
            button.setAccessibleName(label)
            button.clicked.connect(lambda _checked=False, p=page_id: self.show_page(p))
            layout.addWidget(button)
        layout.addStretch(1)
        return frame

    def _build_page(self, page_id: PageId) -> QWidget:
        definition = PAGE_DEFINITIONS[page_id]
        page = QWidget()
        page.setObjectName(page_id.value)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(16)

        title = QLabel(definition.title)
        title.setObjectName("pageTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(title)
        for widget in self._page_content(page_id):
            layout.addWidget(widget)
        layout.addStretch(1)

        for action in definition.primary_actions:
            layout.addWidget(self._action_button(action, primary=True))
        for action in definition.secondary_actions:
            layout.addWidget(self._action_button(action, primary=False))
        return page

    def _action_button(self, action: str, *, primary: bool) -> QPushButton:
        label = _ACTION_LABELS[action]
        button = QPushButton(label)
        button.setObjectName(action)
        button.setAccessibleName(label)
        button.setMinimumHeight(48)
        button.setProperty("importance", "primary" if primary else "secondary")
        if self._on_action is not None:
            if action == "STOP_SCREENING":
                button.clicked.connect(self._confirm_stop)
            else:
                button.clicked.connect(
                    lambda _checked=False, selected=action: self._on_action(selected)
                )
        return button

    def _confirm_stop(self, _checked: bool = False) -> None:
        if not self._stop_confirmation_pending:
            self._stop_confirmation_pending = True
            button = self._pages[PageId.ACQUIRING].findChild(
                QPushButton,
                "STOP_SCREENING",
            )
            button.setText("再次点击确认停止")
            self._notice_banner.setText("停止后本次检测将标记为未完成")
            self._notice_banner.show()
            return
        self._stop_confirmation_pending = False
        self._on_action("STOP_SCREENING")

    def _reset_stop_confirmation(self) -> None:
        self._stop_confirmation_pending = False
        page = self._pages.get(PageId.ACQUIRING)
        if page is None:
            return
        button = page.findChild(QPushButton, "STOP_SCREENING")
        if button is not None:
            button.setText(_ACTION_LABELS["STOP_SCREENING"])

    def _present_result_state(self, state: WorkflowState) -> None:
        page = self._pages[PageId.RESULT]
        report_ready = state.report_status is ReportStatus.BASIC_READY
        retry_required = state.validity in {
            SessionValidity.INVALID,
            SessionValidity.INCOMPLETE,
            SessionValidity.FAILED,
        }
        page.findChild(QPushButton, "VIEW_BASIC_REPORT").setVisible(report_ready)
        page.findChild(QPushButton, "START_NEXT_SCREENING").setVisible(report_ready)
        page.findChild(QPushButton, "RETRY_SCREENING").setVisible(retry_required)
        basic_status = page.findChild(QLabel, "basicReportStatus")
        full_status = page.findChild(QLabel, "fullReportStatus")
        if report_ready:
            basic_status.setText(f"✓ 基础报告已生成（版本 {state.report_version}）")
            full_status.setText("⟳ 完整分析正在后台生成")
        elif retry_required:
            basic_status.setText("本次检测未完成，请重新站稳后检测")
            full_status.clear()
        else:
            basic_status.setText("正在完成本地处理")
            full_status.clear()

    def _page_content(self, page_id: PageId) -> tuple[QWidget, ...]:
        if page_id is PageId.WORKBENCH:
            recent = QTableWidget(0, 3)
            recent.setObjectName("recentScreenings")
            recent.setHorizontalHeaderLabels(("编号", "时间", "报告状态"))
            recent.setAccessibleName("最近检测")
            return (
                self._status_label("deviceSummary", "压力设备：等待检查"),
                self._status_label("syncSummary", "数据同步：等待检查"),
                self._status_label("pendingSummary", "待同步数据：--"),
                recent,
            )
        if page_id is PageId.SUBJECT_IDENTIFICATION:
            id_type = QComboBox()
            id_type.setObjectName("subjectIdTypeInput")
            id_type.setAccessibleName("机构编号类型")
            for label, value in (
                ("机构档案号", "institution_record"),
                ("病历号", "medical_record_number"),
                ("体检号", "examination_number"),
                ("住户编号", "resident_number"),
            ):
                id_type.addItem(label, value)
            external_id = QLineEdit()
            external_id.setObjectName("subjectExternalIdInput")
            external_id.setAccessibleName("机构档案号、病历号、体检号或住户编号")
            lookup = QPushButton("查找")
            lookup.setObjectName("lookupSubjectButton")
            lookup.setAccessibleName("查找受试者")
            lookup.setMinimumHeight(48)
            if self._on_action is not None:
                lookup.clicked.connect(
                    lambda _checked=False: self._on_action("LOOKUP_SUBJECT")
                )
            return (
                id_type,
                external_id,
                lookup,
                self._status_label("subjectMatchSummary", "输入编号后查找档案"),
            )
        if page_id is PageId.PROFILE:
            age = QComboBox()
            age.setObjectName("ageBandInput")
            age.setAccessibleName("年龄段（选填）")
            for label, value in (
                ("请选择", None),
                ("18–39", "18-39"),
                ("40–59", "40-59"),
                ("60–69", "60-69"),
                ("70–79", "70-79"),
                ("80+", "80+"),
            ):
                age.addItem(label, value)
            sex = QComboBox()
            sex.setObjectName("sexInput")
            sex.setAccessibleName("性别（选填）")
            for label, value in (
                ("请选择", None),
                ("女", "female"),
                ("男", "male"),
                ("其他", "other"),
            ):
                sex.addItem(label, value)
            height = QLineEdit()
            height.setObjectName("heightInput")
            height.setAccessibleName("身高厘米（选填）")
            weight = QLineEdit()
            weight.setObjectName("weightInput")
            weight.setAccessibleName("体重千克（选填）")
            conditions = QLineEdit()
            conditions.setObjectName("conditionTagsInput")
            conditions.setAccessibleName("基础情况标签（选填）")
            injuries = QLineEdit()
            injuries.setObjectName("injuryTagsInput")
            injuries.setAccessibleName("既往损伤标签（选填）")
            return (
                self._profile_row(
                    "年龄段",
                    "ageBandState",
                    "年龄段提供状态",
                    age,
                ),
                self._profile_row(
                    "性别",
                    "sexState",
                    "性别提供状态",
                    sex,
                ),
                self._profile_row(
                    "身高（厘米）",
                    "heightState",
                    "身高提供状态",
                    height,
                ),
                self._profile_row(
                    "体重（千克）",
                    "weightState",
                    "体重提供状态",
                    weight,
                ),
                self._profile_row(
                    "基础情况/基础病",
                    "conditionTagsState",
                    "基础情况提供状态",
                    conditions,
                ),
                self._profile_row(
                    "既往损伤",
                    "injuryTagsState",
                    "既往损伤提供状态",
                    injuries,
                ),
            )
        if page_id is PageId.CONSENT:
            required = QCheckBox("我已了解并同意上述必要处理")
            required.setObjectName("requiredConsent")
            required.setAccessibleName("必要处理授权")
            research = QCheckBox("我同意将去标识化数据用于额外算法研究（选填）")
            research.setObjectName("researchConsent")
            research.setAccessibleName("额外算法研究授权（选填）")
            policy = QPushButton("查看完整信息处理规则")
            policy.setObjectName("policyLink")
            policy.setAccessibleName("查看完整信息处理规则")
            policy.setMinimumHeight(48)
            return (required, research, policy)
        if page_id is PageId.PREFLIGHT:
            return tuple(
                self._status_label(name, text)
                for name, text in (
                    ("deviceCheck", "压力设备：等待检查"),
                    ("storageCheck", "数据存储：等待检查"),
                    ("calibrationCheck", "标定状态：等待检查"),
                    ("syncCheck", "数据同步：等待检查"),
                    ("zeroLoadCheck", "零载状态：等待检查"),
                )
            )
        if page_id is PageId.POSITION_GUIDANCE:
            return (
                self._status_label(
                    "positionStatus",
                    "双脚自然站立，保持身体放松",
                ),
                self._status_label("countdownLabel", "检测到稳定站位后将自动开始"),
            )
        if page_id is PageId.ACQUIRING:
            heatmap = QFrame()
            heatmap.setObjectName("heatmapHost")
            heatmap.setAccessibleName("实时压力热力图")
            heatmap.setMinimumHeight(320)
            heatmap.setStyleSheet("background: #edf2f7; border: 1px solid #64748b;")
            return (
                heatmap,
                self._status_label("remainingTime", "剩余 --:--"),
                self._status_label(
                    "acquisitionInstruction",
                    "请保持自然站立，不要说话或大幅移动",
                ),
                self._status_label("acquisitionStatus", "当前状态：等待采集"),
            )
        if page_id is PageId.RESULT:
            return (
                self._status_label("basicReportStatus", "基础报告：等待生成"),
                self._status_label("fullReportStatus", "完整分析：等待同步"),
            )
        if page_id is PageId.RECORDS:
            search = QLineEdit()
            search.setObjectName("recordSearchInput")
            search.setAccessibleName("按机构编号搜索检测记录")
            records = QTableWidget(0, 5)
            records.setObjectName("recordsTable")
            records.setAccessibleName("检测记录")
            records.setHorizontalHeaderLabels(
                ("编号", "时间", "测试项目", "报告状态", "操作")
            )
            return (search, records)
        if page_id is PageId.REPORT_PREVIEW:
            preview = QFrame()
            preview.setObjectName("reportPreview")
            preview.setAccessibleName("A4 报告分页预览")
            preview.setMinimumHeight(420)
            preview.setStyleSheet("background: white; border: 1px solid #94a3b8;")
            return (preview,)
        if page_id is PageId.SUPPORT:
            return (
                self._status_label("deviceHealth", "压力设备：等待检查"),
                self._status_label("syncHealth", "数据同步：等待检查"),
                self._status_label("pendingCount", "待同步数据：--"),
                self._status_label("appVersion", "软件版本：--"),
            )
        return ()

    @staticmethod
    def _status_label(object_name: str, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName(object_name)
        label.setAccessibleName(text)
        label.setWordWrap(True)
        return label

    @staticmethod
    def _field_state_combo(object_name: str, accessible_name: str) -> QComboBox:
        selector = QComboBox()
        selector.setObjectName(object_name)
        selector.setAccessibleName(accessible_name)
        for label, value in (
            ("已填写", "PROVIDED"),
            ("明确无", "NONE_REPORTED"),
            ("未知/未询问", "UNKNOWN"),
            ("拒绝提供", "DECLINED"),
            ("不适用", "NOT_APPLICABLE"),
        ):
            selector.addItem(label, value)
        selector.setCurrentIndex(2)
        return selector

    @classmethod
    def _profile_row(
        cls,
        label_text: str,
        state_name: str,
        state_accessible_name: str,
        value_widget: QWidget,
    ) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        label = QLabel(label_text)
        label.setFixedWidth(150)
        state = cls._field_state_combo(state_name, state_accessible_name)
        state.setFixedWidth(180)
        layout.addWidget(label)
        layout.addWidget(state)
        layout.addWidget(value_widget, 1)
        return row
