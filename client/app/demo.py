from __future__ import annotations

import sys
from datetime import date, datetime

import numpy as np
from PySide6.QtWidgets import QApplication

from client.app.app_icon import application_icon
from client.hardware_standardization.runtime import active_hardware_runtime

from client.local_analysis.display import build_display_frame
from client.reporting.models import (
    BasicReportDocument,
    ReportMetric,
    ReportStatus as ReportDocumentStatus,
)
from client.workflow.models import ReportStatus, WorkflowState
from client.workflow.state_machine import ScreeningStep

from .pages import PageId
from .qt_shell import ScreeningWindow
from .ui_models import DashboardSnapshot, ScreeningRecordRow, SupportSnapshot


class DesignDemoController:
    """Development-only controller for visually reviewing the operator flow."""

    _NEXT_PAGE = {
        "START_NEW_SCREENING": PageId.SUBJECT_IDENTIFICATION,
        "CONFIRM_SUBJECT": PageId.PROFILE,
        "CREATE_ANONYMOUS_SUBJECT": PageId.PROFILE,
        "SAVE_PROFILE": PageId.CONSENT,
        "SKIP_PROFILE": PageId.CONSENT,
        "CONFIRM_CONSENT": PageId.PREFLIGHT,
        "RECHECK": PageId.PREFLIGHT,
        "ENTER_POSITION": PageId.POSITION_GUIDANCE,
        "RETRY_SCREENING": PageId.PREFLIGHT,
        "VIEW_BASIC_REPORT": PageId.REPORT_PREVIEW,
        "VIEW_SELECTED_REPORT": PageId.REPORT_PREVIEW,
        "START_NEXT_SCREENING": PageId.SUBJECT_IDENTIFICATION,
        "RECHECK_SYSTEM": PageId.SUPPORT,
        "EXPORT_DIAGNOSTIC": PageId.SUPPORT,
    }

    def __init__(self) -> None:
        self.window = ScreeningWindow(on_action=self.dispatch)
        self._records = (
            ScreeningRecordRow(
                "**2781", "07-21 10:20", "静态筛查", "完整报告", date(2026, 7, 21)
            ),
            ScreeningRecordRow(
                "临时034", "07-21 10:05", "静态筛查", "基础报告", date(2026, 7, 21)
            ),
            ScreeningRecordRow(
                "**1052", "07-21 09:42", "静态筛查", "分析中", date(2026, 7, 21)
            ),
            ScreeningRecordRow(
                "**0973", "07-21 09:18", "静态筛查", "未完成", date(2026, 7, 21)
            ),
            ScreeningRecordRow(
                "**0841", "07-21 08:55", "静态筛查", "完整报告", date(2026, 7, 21)
            ),
        )
        self.window.present_dashboard(
            DashboardSnapshot(
                organization_name="安康体检中心 · A 区筛查终端",
                device_status="设备已就绪",
                sync_status="数据已同步",
                pending_summary="待同步数据：0 次",
                recent_records=self._records,
            )
        )
        self.window.present_records(self._records)
        self.window.present_support(
            SupportSnapshot("已连接", "正常", "待同步数据：0 次", "1.0.0-demo")
        )
        self._report_document = BasicReportDocument(
            report_id="demo-report-001",
            version=1,
            status=ReportDocumentStatus.BASIC_READY,
            kind="basic",
            session_id="demo-session-001",
            analysis_result_id="demo-analysis-001",
            subject_display_id="**2781",
            captured_at=datetime(2026, 7, 21, 10, 20),
            generated_at=datetime(2026, 7, 21, 10, 21),
            protocol_id="standard-static-bilateral",
            protocol_version="1.0.0-pilot",
            metrics=(
                ReportMetric("left", "左侧相对负重", 51.2, "percent", "1"),
                ReportMetric("right", "右侧相对负重", 48.8, "percent", "1"),
            ),
            relative_heatmap=((0.0, 1.0),),
            summary="本次筛查已完成基础分析，可在完整分析完成后查看更新版本。",
            disclaimer="本报告用于健康筛查与风险提示，不提供临床诊断。",
            provenance=("development-demo",),
        )
        self._seed_display_frame()

    def dispatch(self, action: str) -> None:
        if action == "LOOKUP_SUBJECT":
            self.window.set_subject_match_summary(
                "已找到唯一档案：编号 **2781 · 年龄 64 岁 · 性别 女 · 上次检测 07-12"
            )
            return
        if action == "START_ACQUISITION":
            self.window.present_state(
                WorkflowState(
                    step=ScreeningStep.ACQUIRING,
                    remaining_seconds=30,
                    acquisition_instruction="请保持自然站立，不要说话或大幅移动",
                )
            )
            return
        if action == "STOP_SCREENING":
            self.window.present_state(
                WorkflowState(
                    step=ScreeningStep.BASIC_REPORT,
                    report_status=ReportStatus.BASIC_READY,
                    report_version=1,
                )
            )
            return
        if action in {"VIEW_BASIC_REPORT", "VIEW_SELECTED_REPORT"}:
            self.window.present_report_document(self._report_document)
            self.window.show_page(PageId.REPORT_PREVIEW)
            return
        self.window.show_page(self._NEXT_PAGE.get(action, PageId.WORKBENCH))

    def _seed_display_frame(self) -> None:
        # Four smooth pressure lobes create a believable bilateral standing
        # preview while remaining entirely local development data.
        geometry = active_hardware_runtime().display_geometry
        row_indexes, column_indexes = np.indices(geometry.matrix_shape)
        counts = np.zeros(geometry.matrix_shape, dtype=np.float64)
        scale_x = geometry.columns / 64.0
        scale_y = geometry.rows / 48.0
        for center_x, center_y, amplitude, radius_x, radius_y in (
            (18, 12, 720.0, 3.5, 2.8),
            (18, 33, 1_100.0, 5.5, 4.8),
            (46, 12, 650.0, 3.5, 2.8),
            (46, 33, 950.0, 5.5, 4.8),
        ):
            counts += amplitude * np.exp(
                -(
                    ((column_indexes - center_x * scale_x) / (radius_x * scale_x)) ** 2
                    + ((row_indexes - center_y * scale_y) / (radius_y * scale_y)) ** 2
                )
            )
        self.window.present_display_frame(
            build_display_frame(
                counts,
                sequence=12,
                captured_monotonic_seconds=12.0,
                cop_trail=((28.0, 24.0), (30.0, 24.0)),
                total_trend=(800.0, 900.0, 1_000.0),
            )
        )


def run_design_demo() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setWindowIcon(application_icon())
    controller = DesignDemoController()
    controller.window.resize(1440, 900)
    controller.window.show()
    return app.exec()
