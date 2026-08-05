from __future__ import annotations

import pytest
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QLabel

from client.app.position_guide import StageGuidanceWidget


@pytest.mark.parametrize(
    ("stage_index", "body_asset", "feet_asset"),
    (
        (1, "stage-1-body.png", "stage-1-feet.png"),
        (2, "stage-2-body.png", "stage-2-feet.png"),
        (3, "stage-3-body.png", "stage-3-feet.png"),
        (4, "stage-4-body.png", "stage-4-feet.jpg"),
    ),
)
def test_stage_guidance_loads_the_numbered_body_and_feet_images(
    qtbot, stage_index, body_asset, feet_asset
) -> None:
    widget = StageGuidanceWidget()
    qtbot.addWidget(widget)

    widget.set_stage(stage_index)

    body = widget.findChild(QLabel, "stageBodyGuide")
    feet = widget.findChild(QLabel, "stageFeetGuide")
    assert body is not None
    assert feet is not None
    assert not body.pixmap().isNull()
    assert not feet.pixmap().isNull()
    assert widget.property("guidanceStage") == stage_index
    assert widget.property("guidanceBodyAsset") == body_asset
    assert widget.property("guidanceFeetAsset") == feet_asset


def test_stage_guidance_preserves_source_aspect_ratios_when_resized(qtbot) -> None:
    widget = StageGuidanceWidget()
    qtbot.addWidget(widget)
    widget.resize(640, 300)
    widget.show()
    qtbot.wait(50)

    for label_name, asset_name in (
        ("stageBodyGuide", "stage-3-body.png"),
        ("stageFeetGuide", "stage-3-feet.png"),
    ):
        widget.set_stage(3)
        label = widget.findChild(QLabel, label_name)
        assert label is not None
        source = QImage(str(widget.asset_root / asset_name))
        pixmap = label.pixmap()
        assert not source.isNull()
        assert not pixmap.isNull()
        assert pixmap.width() <= label.width()
        assert pixmap.height() <= label.height()
        assert pixmap.width() / pixmap.height() == pytest.approx(
            source.width() / source.height(), rel=0.015
        )
