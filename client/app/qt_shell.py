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

from client.workflow.models import WorkflowState

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
            button.clicked.connect(
                lambda _checked=False, selected=action: self._on_action(selected)
            )
        return button

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
            external_id = QLineEdit()
            external_id.setObjectName("subjectExternalIdInput")
            external_id.setAccessibleName("机构档案号、病历号、体检号或住户编号")
            lookup = QPushButton("查找")
            lookup.setObjectName("lookupSubjectButton")
            lookup.setAccessibleName("查找受试者")
            lookup.setMinimumHeight(48)
            return (
                external_id,
                lookup,
                self._status_label("subjectMatchSummary", "输入编号后查找档案"),
            )
        if page_id is PageId.PROFILE:
            age = QComboBox()
            age.setObjectName("ageBandInput")
            age.setAccessibleName("年龄段（选填）")
            age.addItems(("未提供", "18–39", "40–59", "60–69", "70–79", "80+"))
            sex = QComboBox()
            sex.setObjectName("sexInput")
            sex.setAccessibleName("性别（选填）")
            sex.addItems(("未提供", "女", "男", "其他", "拒绝提供"))
            height = QLineEdit()
            height.setObjectName("heightInput")
            height.setAccessibleName("身高厘米（选填）")
            weight = QLineEdit()
            weight.setObjectName("weightInput")
            weight.setAccessibleName("体重千克（选填）")
            return (age, sex, height, weight)
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
