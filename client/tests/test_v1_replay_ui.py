from __future__ import annotations

from PySide6.QtWidgets import QLabel, QProgressBar

from client.app.pages import PageId
from client.app.qt_shell import ScreeningWindow
from client.workflow.models import WorkflowState
from client.workflow.state_machine import ScreeningStep


def test_replay_acquisition_shows_stage_source_and_20_second_progress(qtbot) -> None:
    window = ScreeningWindow()
    qtbot.addWidget(window)

    window.present_state(
        WorkflowState(
            step=ScreeningStep.ACQUIRING,
            stage_index=2,
            stage_count=4,
            stage_title="第二段：并足闭眼",
            acquisition_instruction="请保持并足闭眼站立",
            remaining_seconds=10,
            data_source_mode="REPLAY_DEBUG",
        )
    )

    page = window.page_widget(PageId.ACQUIRING)
    assert page.findChild(QLabel, "acquisitionStage").text() == "第 2/4 段 · 第二段：并足闭眼"
    assert page.findChild(QLabel, "acquisitionSource").text() == "回放调试数据"
    assert page.findChild(QProgressBar, "acquisitionProgress").value() == 50
