from __future__ import annotations

import numpy as np
from PySide6.QtWidgets import QLabel

from client.app.heatmap import HeatmapWidget
from client.app.heatmap_display import HeatmapDisplayConfig
from client.app.pages import PageId
from client.app.qt_shell import ScreeningWindow
from client.local_analysis.display import build_display_frame


def test_acquisition_view_renders_heatmap_cop_and_redundant_text_summary(qtbot) -> None:
    counts = np.zeros((48, 64), dtype=np.float64)
    counts[20, 10] = 1500.0
    counts[20, 53] = 500.0
    frame = build_display_frame(
        counts,
        sequence=7,
        captured_monotonic_seconds=12.5,
        cop_trail=(),
        total_trend=(),
    )
    window = ScreeningWindow()
    qtbot.addWidget(window)

    window.present_display_frame(frame)

    page = window.page_widget(PageId.ACQUIRING)
    heatmap = page.findChild(HeatmapWidget, "heatmapHost")
    assert heatmap.display_frame is frame
    assert "COP" in page.findChild(QLabel, "copSummary").text()
    assert "左 75.0%" in page.findChild(QLabel, "loadSummary").text()
    assert "设备帧 #7" in page.findChild(QLabel, "frameFreshness").text()
    assert "48×64" in heatmap.accessibleName()


def test_heatmap_widget_high_dpi_render_is_not_blank(qtbot) -> None:
    counts = np.zeros((48, 64), dtype=np.float64)
    counts[20, 10] = 1000.0
    frame = build_display_frame(
        counts,
        sequence=1,
        captured_monotonic_seconds=1.0,
        cop_trail=(),
        total_trend=(),
    )
    widget = HeatmapWidget()
    qtbot.addWidget(widget)
    widget.resize(640, 480)
    widget.set_display_frame(frame)
    widget.show()
    qtbot.waitExposed(widget)

    image = widget.grab().toImage()

    assert image.devicePixelRatio() >= 1.0
    assert image.pixelColor(image.width() // 2, image.height() // 2).isValid()
    assert image.pixelColor(105, 205) != image.pixelColor(0, 0)


def test_widget_refinement_keeps_display_frame_metrics_and_source_pixels_unchanged(qtbot) -> None:
    counts = np.zeros((48, 64), dtype=np.float64)
    counts[20:25, 26:31] = 800.0
    counts[5, 5] = 1_600.0
    frame = build_display_frame(
        counts,
        sequence=9,
        captured_monotonic_seconds=13.0,
        cop_trail=(),
        total_trend=(),
    )
    before_metrics = (
        frame.cop_x,
        frame.cop_y,
        frame.left_load_percent,
        frame.right_load_percent,
        frame.total_relative_load,
    )
    before_source = frame.relative_heatmap
    widget = HeatmapWidget()
    qtbot.addWidget(widget)

    widget.set_display_frame(frame)

    assert widget.display_frame is frame
    assert frame.relative_heatmap == before_source
    assert (
        frame.cop_x,
        frame.cop_y,
        frame.left_load_percent,
        frame.right_load_percent,
        frame.total_relative_load,
    ) == before_metrics
    assert widget.rendered_heatmap[5][5] == 0.0
    assert max(max(row) for row in widget.rendered_heatmap[20:25]) > 0.0

    unrefined = HeatmapWidget(display_config=HeatmapDisplayConfig(enabled=False))
    qtbot.addWidget(unrefined)
    unrefined.set_display_frame(frame)

    assert unrefined.rendered_heatmap == frame.relative_heatmap
    assert unrefined.display_frame is frame
    assert frame.relative_heatmap == before_source


def test_widget_remains_bounded_and_renderable_during_continuous_high_dpi_refresh(qtbot) -> None:
    widget = HeatmapWidget()
    qtbot.addWidget(widget)
    widget.resize(960, 720)
    widget.show()

    for sequence in range(24):
        counts = np.zeros((48, 64), dtype=np.float64)
        counts[18:25, 25:32] = 600.0 + sequence
        counts[5, 5] = 1_600.0 if sequence % 2 else 0.0
        widget.set_display_frame(
            build_display_frame(
                counts,
                sequence=sequence,
                captured_monotonic_seconds=sequence / 12.0,
                cop_trail=(),
                total_trend=(),
            )
        )

    image = widget.grab().toImage()
    rendered = np.asarray(widget.rendered_heatmap)

    assert image.devicePixelRatio() >= 1.0
    assert image.pixelColor(image.width() // 2, image.height() // 2).isValid()
    assert rendered.shape == (48, 64)
    assert np.all(np.isfinite(rendered))
    assert np.all((rendered >= 0.0) & (rendered <= 1.0))
