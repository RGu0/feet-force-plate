"""Generate deterministic before/after proof for display-only heatmap refinement."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PySide6.QtGui import QColor, QImage

from client.app.heatmap_display import HeatmapDisplayRefiner


def _fixture() -> np.ndarray:
    rows, columns = np.indices((48, 64))
    values = np.zeros((48, 64), dtype=np.float64)
    for center_x, center_y, amplitude, radius_x, radius_y in (
        (22, 15, 0.65, 3.5, 3.0),
        (22, 29, 0.92, 5.0, 5.0),
        (42, 15, 0.58, 3.5, 3.0),
        (42, 29, 0.84, 5.0, 5.0),
    ):
        values += amplitude * np.exp(
            -(((columns - center_x) / radius_x) ** 2 + ((rows - center_y) / radius_y) ** 2)
        )
    values[values < 0.08] = 0.0
    values[29, 22] = 0.0  # enclosed low point
    values[5, 5] = 1.0  # isolated high point
    return values


def _as_tuple(values: np.ndarray) -> tuple[tuple[float, ...], ...]:
    return tuple(tuple(float(value) for value in row) for row in values)


def _color(value: float) -> QColor:
    bounded = max(0.0, min(1.0, float(value)))
    if bounded <= 0.015:
        return QColor("#F6FAFD")
    stops = (
        QColor("#2D4FA8"),
        QColor("#1F9FCE"),
        QColor("#63C685"),
        QColor("#F0C24A"),
        QColor("#E25539"),
    )
    position = bounded * (len(stops) - 1)
    lower = int(position)
    upper = min(lower + 1, len(stops) - 1)
    ratio = position - lower
    start, end = stops[lower], stops[upper]
    return QColor(
        round(start.red() + (end.red() - start.red()) * ratio),
        round(start.green() + (end.green() - start.green()) * ratio),
        round(start.blue() + (end.blue() - start.blue()) * ratio),
    )


def _write(values: np.ndarray, path: Path) -> None:
    image = QImage(64, 48, QImage.Format.Format_RGBA8888)
    image.fill(QColor("#F6FAFD"))
    for row, cells in enumerate(values):
        for column, value in enumerate(cells):
            image.setPixelColor(column, row, _color(float(value)))
    if not image.scaled(640, 480).save(str(path), "PNG"):
        raise RuntimeError(f"could not write {path}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    source = _fixture()
    refined = np.asarray(HeatmapDisplayRefiner().refine(_as_tuple(source)))
    _write(source, args.output / "heatmap-refinement-before.png")
    _write(refined, args.output / "heatmap-refinement-after.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
