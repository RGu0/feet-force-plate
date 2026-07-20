from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6.QtWidgets import QLabel

from client.app.controller import ApplicationController
from client.app.pages import PageId
from client.local_analysis.display import (
    DisplayRefreshController,
    LatestDisplayFrameMailbox,
    build_display_frame,
)
from client.workflow.models import WorkflowState
from client.workflow.state_machine import ScreeningStep


class _Coordinator:
    def __init__(self) -> None:
        self._state = WorkflowState(
            step=ScreeningStep.ACQUIRING,
            remaining_seconds=30,
            acquisition_instruction="请保持自然站立",
        )

    @property
    def state(self) -> WorkflowState:
        return self._state

    def observe_acquisition_elapsed(self, *, elapsed_seconds: int) -> int:
        remaining = max(0, 30 - elapsed_seconds)
        self._state = WorkflowState(
            step=ScreeningStep.ACQUIRING,
            remaining_seconds=remaining,
            acquisition_instruction="请保持自然站立",
        )
        return remaining

    def export_current_report(self, destination: Path) -> None:
        _ = destination

    def print_current_report(self) -> None: ...


def test_workflow_clock_remains_accurate_when_no_new_display_or_upload_event_arrives(qtbot) -> None:
    mailbox = LatestDisplayFrameMailbox()
    counts = np.zeros((48, 64), dtype=np.float64)
    counts[20, 10] = 1000.0
    mailbox.publish(
        build_display_frame(
            counts,
            sequence=1,
            captured_monotonic_seconds=1.0,
            cop_trail=(),
            total_trend=(),
        )
    )
    controller = ApplicationController(
        _Coordinator(),
        display_refresh=DisplayRefreshController(
            mailbox,
            maximum_refresh_hz=30.0,
        ),
    )
    qtbot.addWidget(controller.window)

    assert controller.on_display_tick(0.0)
    assert not controller.on_display_tick(1.0)
    controller.on_acquisition_elapsed(5)

    remaining = controller.window.page_widget(PageId.ACQUIRING).findChild(
        QLabel,
        "remainingTime",
    )
    assert remaining.text() == "剩余 00:25"
