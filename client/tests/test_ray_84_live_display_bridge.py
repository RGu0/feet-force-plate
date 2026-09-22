from __future__ import annotations

import numpy as np
from PySide6.QtWidgets import QLabel

from client.app.controller import ApplicationController
from client.app.heatmap import HeatmapWidget
from client.app.live_display import LiveDisplayProjection
from client.app.pages import PageId
from client.device.acquisition import LatestFrameMailbox
from client.device.protocol import RawFrame
from client.hardware_standardization.live_processing import (
    DoP4864LiveFrameStandardizer,
    replay_debug_profile,
)
from client.local_analysis.display import DisplayRefreshController, LatestDisplayFrameMailbox
from client.workflow.models import WorkflowState
from client.workflow.state_machine import ScreeningStep


def _raw_frame(sequence: int, *, left: int, right: int) -> RawFrame:
    values = np.zeros((48, 64), dtype=np.uint8)
    values[20, 10] = left
    values[20, 53] = right
    values.setflags(write=False)
    return RawFrame(
        values=values,
        host_monotonic_ns=sequence * 50_000_000,
        host_wall_time_ns=sequence,
        source_index=sequence,
        device_frame_seq=None,
        device_timestamp_ns=None,
        quality_flags=frozenset({"SOURCE_INTEGRITY_UNVERIFIED"}),
    )


def _standardizer() -> DoP4864LiveFrameStandardizer:
    return DoP4864LiveFrameStandardizer(replay_debug_profile(fixture_sha256="0" * 64))


def test_live_display_projection_copies_new_hardware_frames_without_mutating_source() -> None:
    hardware = LatestFrameMailbox()
    display = LatestDisplayFrameMailbox()
    bridge = LiveDisplayProjection(
        source=hardware, destination=display, standardizer=_standardizer()
    )
    source = _raw_frame(7, left=150, right=50)
    source_before = source.values.copy()
    hardware.publish(source)

    first = bridge.poll()

    assert first is not None
    assert first.sequence == 7
    assert first.cop_x is not None
    assert first.left_load_percent == 75.0
    assert np.array_equal(source.values, source_before)
    assert not source.values.flags.writeable
    assert bridge.poll() is None
    hardware.publish(_raw_frame(8, left=90, right=110))

    second = bridge.poll()

    assert second is not None
    assert second.sequence == 8
    assert len(second.cop_trail) == 2
    assert len(second.total_trend) == 2
    assert display.take_latest(after_sequence=-1) is second


class _AcquiringCoordinator:
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
        return max(0, 30 - elapsed_seconds)

    def export_current_report(self, destination) -> None:
        _ = destination

    def print_current_report(self) -> None: ...


def test_starting_next_stage_accepts_reconnected_frame_sequence_and_clears_stale_image(
    qtbot,
) -> None:
    class _StageCoordinator(_AcquiringCoordinator):
        def start_acquisition(self) -> bool:
            return True

    hardware = LatestFrameMailbox()
    display = LatestDisplayFrameMailbox()
    controller = ApplicationController(
        _StageCoordinator(),
        display_refresh=DisplayRefreshController(display, maximum_refresh_hz=30.0),
        live_display=LiveDisplayProjection(
            source=hardware, destination=display, standardizer=_standardizer()
        ),
    )
    qtbot.addWidget(controller.window)
    controller.window.show()
    hardware.publish(_raw_frame(12, left=160, right=40))
    controller._on_live_display_timer()

    page = controller.window.page_widget(PageId.ACQUIRING)
    heatmap = page.findChild(HeatmapWidget, "heatmapHost")
    assert heatmap is not None and heatmap.display_frame is not None
    assert heatmap.display_frame.sequence == 12

    assert controller._start_acquisition()

    assert heatmap.display_frame is None
    controller._on_live_display_timer()
    assert heatmap.display_frame is None
    hardware.publish(_raw_frame(0, left=0, right=200))
    qtbot.wait(40)
    controller._on_live_display_timer()

    assert heatmap.display_frame is not None
    assert heatmap.display_frame.sequence == 0
    assert "设备帧 #0" in page.findChild(QLabel, "frameFreshness").text()
    assert "左 0.0% / 右 100.0%" in page.findChild(QLabel, "loadSummary").text()


def test_qt_timer_projects_hardware_latest_frame_into_p07(qtbot) -> None:
    hardware = LatestFrameMailbox()
    display = LatestDisplayFrameMailbox()
    coordinator = _AcquiringCoordinator()
    controller = ApplicationController(
        coordinator,
        display_refresh=DisplayRefreshController(display, maximum_refresh_hz=30.0),
        live_display=LiveDisplayProjection(
            source=hardware, destination=display, standardizer=_standardizer()
        ),
    )
    qtbot.addWidget(controller.window)
    controller.window.show()
    assert controller._live_display_timer.interval() == round(1_000 / 30.0)
    hardware.publish(_raw_frame(11, left=160, right=40))

    page = controller.window.page_widget(PageId.ACQUIRING)
    freshness = page.findChild(QLabel, "frameFreshness")
    qtbot.waitUntil(lambda: "设备帧 #11" in freshness.text(), timeout=1_000)

    assert "左 80.0%" in page.findChild(QLabel, "loadSummary").text()
    coordinator._state = WorkflowState(step=ScreeningStep.BASIC_REPORT)
    controller.refresh()
    assert not controller._live_display_timer.isActive()
