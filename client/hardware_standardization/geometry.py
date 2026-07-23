"""Board-local point layouts; no subject-coordinate transforms belong here."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from math import isfinite

from .models import CellStatus, PhysicalArrayCell


@dataclass(frozen=True, slots=True)
class BoardCoordinateLayout:
    geometry_version: str
    cells: tuple[PhysicalArrayCell, ...]
    coordinate_frame: str = "BOARD_TOP_LEFT_X_RIGHT_Y_DOWN"

    def __post_init__(self) -> None:
        if not self.geometry_version:
            raise ValueError("geometry_version is required")
        if self.coordinate_frame != "BOARD_TOP_LEFT_X_RIGHT_Y_DOWN":
            raise ValueError("only board-local coordinates are supported")
        if not self.cells:
            raise ValueError("layout must contain cells")
        if len({cell.cell_id for cell in self.cells}) != len(self.cells):
            raise ValueError("layout cell IDs must be unique")
        if len({cell.source_index for cell in self.cells}) != len(self.cells):
            raise ValueError("layout source indices must be unique")

    @classmethod
    def top_left_grid(
        cls,
        *,
        rows: int,
        columns: int,
        pitch_x_mm: float,
        pitch_y_mm: float,
        geometry_version: str,
        nominal_active_area_mm2: float | None,
        origin_x_mm: float = 0.0,
        origin_y_mm: float = 0.0,
    ) -> BoardCoordinateLayout:
        if rows <= 0 or columns <= 0:
            raise ValueError("rows and columns must be positive")
        if not isfinite(pitch_x_mm) or not isfinite(pitch_y_mm) or min(pitch_x_mm, pitch_y_mm) <= 0:
            raise ValueError("grid pitches must be positive finite values")
        cells = tuple(
            PhysicalArrayCell(
                cell_id=f"r{row}-c{column}",
                source_index=column * rows + row,
                board_x_mm=origin_x_mm + column * pitch_x_mm,
                board_y_mm=origin_y_mm + row * pitch_y_mm,
                nominal_active_area_mm2=nominal_active_area_mm2,
                status=CellStatus.ACTIVE,
            )
            for column in range(columns)
            for row in range(rows)
        )
        return cls(geometry_version=geometry_version, cells=cells)

    @classmethod
    def from_cells(
        cls,
        *,
        geometry_version: str,
        cells: tuple[tuple[str, int, float, float, float | None], ...],
    ) -> BoardCoordinateLayout:
        return cls(
            geometry_version=geometry_version,
            cells=tuple(
                sorted(
                    (
                        PhysicalArrayCell(
                            cell_id=cell_id,
                            source_index=source_index,
                            board_x_mm=x_mm,
                            board_y_mm=y_mm,
                            nominal_active_area_mm2=area_mm2,
                            status=CellStatus.ACTIVE,
                        )
                        for cell_id, source_index, x_mm, y_mm, area_mm2 in cells
                    ),
                    key=lambda cell: cell.source_index,
                )
            ),
        )

    @property
    def digest(self) -> str:
        payload = {
            "coordinate_frame": self.coordinate_frame,
            "geometry_version": self.geometry_version,
            "cells": [
                {
                    "cell_id": cell.cell_id,
                    "source_index": cell.source_index,
                    "board_x_mm": cell.board_x_mm,
                    "board_y_mm": cell.board_y_mm,
                    "nominal_active_area_mm2": cell.nominal_active_area_mm2,
                    "status": cell.status.value,
                }
                for cell in self.cells
            ],
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

    def cell_by_source_index(self, source_index: int) -> PhysicalArrayCell:
        for cell in self.cells:
            if cell.source_index == source_index:
                return cell
        raise KeyError(source_index)
