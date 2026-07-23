"""Capture deterministic 1440×900 Steady Health UI review frames.

Development-only utility.  It seeds the local read models, never opens a
device/database/network adapter, and is intended for visual regression review.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PySide6.QtWidgets import QApplication

from client.app.demo import DesignDemoController
from client.app.pages import PageId
from client.workflow.models import ReportStatus, WorkflowState
from client.workflow.state_machine import ScreeningStep


CAPTURES = (
    ("P-01-workbench", PageId.WORKBENCH),
    ("P-03-profile", PageId.PROFILE),
    ("P-06-position", PageId.POSITION_GUIDANCE),
    ("P-07-acquiring", PageId.ACQUIRING),
    ("P-08-result", PageId.RESULT),
    ("P-10-report", PageId.REPORT_PREVIEW),
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("/private/tmp/feetforceplate-ui-captures"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    app = QApplication.instance() or QApplication([])
    demo = DesignDemoController()
    window = demo.window
    window.resize(1440, 900)
    window.show()
    app.processEvents()

    demo.dispatch("VIEW_BASIC_REPORT")
    for name, page_id in CAPTURES:
        if page_id is PageId.ACQUIRING:
            window.present_state(
                WorkflowState(
                    step=ScreeningStep.ACQUIRING,
                    remaining_seconds=18,
                    acquisition_instruction="请保持自然站立，\n不要说话或大幅移动。",
                )
            )
        elif page_id is PageId.RESULT:
            window.present_state(
                WorkflowState(
                    step=ScreeningStep.BASIC_REPORT,
                    report_status=ReportStatus.BASIC_READY,
                    report_version=1,
                )
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
