from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QWidget


ASSET_ROOT = Path(__file__).with_name("assets") / "position-guidance"
GUIDANCE_ASSETS = {
    1: ("stage-1-body.png", "stage-1-feet.png"),
    2: ("stage-2-body.png", "stage-2-feet.png"),
    3: ("stage-3-body.png", "stage-3-feet.png"),
    4: ("stage-4-body.png", "stage-4-feet.jpg"),
}


class StageGuidanceWidget(QWidget):
    """Show the approved full-body and foot-placement image for one stage."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("stageGuidance")
        self.setAccessibleName("分段站位引导")
        self.setAccessibleDescription("显示当前动作的全身站姿和双脚站位示意")
        self.setMinimumSize(560, 230)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._body_source = QPixmap()
        self._feet_source = QPixmap()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(24)
        self._body_label = self._image_label("stageBodyGuide", "全身站姿示意")
        self._feet_label = self._image_label("stageFeetGuide", "双脚站位示意")
        layout.addWidget(self._body_label, 1)
        layout.addWidget(self._feet_label, 1)

        self.set_stage(1)

    @property
    def asset_root(self) -> Path:
        return ASSET_ROOT

    def set_stage(self, stage_index: int) -> None:
        try:
            body_name, feet_name = GUIDANCE_ASSETS[stage_index]
        except KeyError as error:
            raise ValueError(f"unsupported guidance stage: {stage_index}") from error
        self._body_source = self._load_asset(body_name)
        self._feet_source = self._load_asset(feet_name)
        self.setProperty("guidanceStage", stage_index)
        self.setProperty("guidanceBodyAsset", body_name)
        self.setProperty("guidanceFeetAsset", feet_name)
        self._scale_images()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._scale_images()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._scale_images()

    def _image_label(self, object_name: str, accessible_name: str) -> QLabel:
        label = QLabel()
        label.setObjectName(object_name)
        label.setAccessibleName(accessible_name)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setScaledContents(False)
        label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        return label

    def _load_asset(self, asset_name: str) -> QPixmap:
        pixmap = QPixmap(str(ASSET_ROOT / asset_name))
        if pixmap.isNull():
            raise RuntimeError(f"unable to load stage guidance asset: {asset_name}")
        return pixmap

    def _scale_images(self) -> None:
        self._set_scaled_pixmap(self._body_label, self._body_source)
        self._set_scaled_pixmap(self._feet_label, self._feet_source)

    @staticmethod
    def _set_scaled_pixmap(label: QLabel, source: QPixmap) -> None:
        if source.isNull():
            return
        available_size = label.contentsRect().size()
        if available_size.isEmpty():
            label.setPixmap(source)
            return
        label.setPixmap(
            source.scaled(
                available_size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
