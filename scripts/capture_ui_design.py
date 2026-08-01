"""Capture deterministic Steady Health UI review frames.

Development-only utility.  It seeds the local read models, never opens a
device/database/network adapter, and is intended for visual regression review.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path

from PySide6.QtWidgets import QApplication, QPushButton

from client.app.demo import DesignDemoController
from client.app.pages import PageId
from client.workflow.models import (
    ClientAction,
    ClientError,
    PreflightCheck,
    ReportStatus,
    SessionValidity,
    WorkflowState,
)
from client.workflow.protocol import PositionGuidanceState, PositionStatus
from client.workflow.state_machine import ScreeningStep


CAPTURES = (
    ("P-01-workbench", PageId.WORKBENCH),
    ("P-02-subject", PageId.SUBJECT_IDENTIFICATION),
    ("P-02-subject-conflict", PageId.SUBJECT_IDENTIFICATION),
    ("P-03-profile", PageId.PROFILE),
    ("P-04-consent", PageId.CONSENT),
    ("P-05-preflight-ok", PageId.PREFLIGHT),
    ("P-05-preflight-fail", PageId.PREFLIGHT),
    ("P-06-position", PageId.POSITION_GUIDANCE),
    ("P-07-acquiring", PageId.ACQUIRING),
    ("P-07-stop-confirm", PageId.ACQUIRING),
    ("P-08-result-ok", PageId.RESULT),
    ("P-08-result-fail", PageId.RESULT),
    ("P-09-records", PageId.RECORDS),
    ("P-10-report", PageId.REPORT_PREVIEW),
    ("P-11-support", PageId.SUPPORT),
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("/private/tmp/feetforceplate-ui-captures"))
    parser.add_argument("--width", type=int, default=1440)
    parser.add_argument("--height", type=int, default=900)
    args = parser.parse_args()
    if args.width <= 0 or args.height <= 0:
        parser.error("--width and --height must be positive integers")
    args.output.mkdir(parents=True, exist_ok=True)

    app = QApplication.instance() or QApplication([])
    demo = DesignDemoController()
    window = demo.window
    window.resize(args.width, args.height)
    window.show()
    app.processEvents()

    for name, page_id in CAPTURES:
        if name == "P-02-subject":
            demo.dispatch("LOOKUP_SUBJECT")
        elif name == "P-02-subject-conflict":
            window.show_subject_conflict()
        elif name == "P-03-profile":
            profile = window.page_widget(PageId.PROFILE)
            for chip in profile.findChildren(QPushButton):
                if chip.text() in {"高血压", "既往下肢损伤"}:
                    chip.click()
        elif name == "P-05-preflight-ok":
            window.present_state(
                WorkflowState(
                    step=ScreeningStep.PREFLIGHT,
                    preflight_checks=(
                        PreflightCheck("device_connected", True, operator_message="已连接"),
                        PreflightCheck("storage_space", True, operator_message="空间充足"),
                        PreflightCheck(
                            "calibration_status",
                            True,
                            operator_message="最近校准 07-20",
                        ),
                        PreflightCheck("data_sync", True, operator_message="已同步"),
                    ),
                    preflight_ready=True,
                )
            )
        elif name == "P-05-preflight-fail":
            window.present_state(
                WorkflowState(
                    step=ScreeningStep.PREFLIGHT,
                    preflight_checks=(
                        PreflightCheck("device_connected", True, operator_message="已连接"),
                        PreflightCheck("storage_space", True, operator_message="空间充足"),
                        PreflightCheck(
                            "calibration_status",
                            True,
                            operator_message="最近校准 07-20",
                        ),
                        PreflightCheck(
                            "data_sync",
                            False,
                            operator_message="等待同步",
                        ),
                    ),
                    error=ClientError(
                        "NETWORK_UNAVAILABLE",
                        "网络待恢复，请检查网络后重新检查",
                        ClientAction.RECHECK,
                    ),
                )
            )
        elif name == "P-06-position":
            window.present_state(
                WorkflowState(
                    step=ScreeningStep.POSITION_GUIDANCE,
                    stage_index=1,
                    stage_count=4,
                    stage_title="第一段：并足睁眼",
                    data_source_mode="REPLAY_DEBUG",
                    position_guidance=PositionGuidanceState(
                        status=PositionStatus.READY,
                        instruction_text="双脚并拢自然站立，睁眼平视前方",
                        countdown_seconds=None,
                        countdown_text="站位已稳定，请点击“开始本段”",
                        manual_start_allowed=True,
                    ),
                )
            )
        elif name in {"P-07-acquiring", "P-07-stop-confirm"}:
            window.present_state(
                WorkflowState(
                    step=ScreeningStep.ACQUIRING,
                    planned_duration_seconds=20,
                    remaining_seconds=18,
                    stage_index=1,
                    stage_count=4,
                    stage_title="第一段：并足睁眼",
                    data_source_mode="REPLAY_DEBUG",
                    acquisition_instruction="请保持自然站立，\n不要说话或大幅移动。",
                )
            )
            if name == "P-07-stop-confirm":
                window.page_widget(PageId.ACQUIRING).findChild(
                    QPushButton, "STOP_SCREENING"
                ).click()
        elif name == "P-08-result-ok":
            window.present_state(
                WorkflowState(
                    step=ScreeningStep.BASIC_REPORT,
                    report_status=ReportStatus.BASIC_READY,
                    report_version=1,
                )
            )
        elif name == "P-08-result-fail":
            window.present_state(
                WorkflowState(
                    step=ScreeningStep.INCOMPLETE,
                    validity=SessionValidity.INVALID,
                )
            )
        elif name == "P-10-report":
            window.present_report_document(
                replace(demo._report_document, kind="FULL")
            )
        window.show_page(page_id)
        app.processEvents()
        target = args.output / f"{name}.png"
        if not window.grab().save(str(target), "PNG"):
            raise RuntimeError(f"unable to write {target}")
        print(target)
    window.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
