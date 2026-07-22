"""Thin DO-P4864 adapter over decoded RawFrame values; never a byte parser."""

from __future__ import annotations

import numpy as np

from client.device.protocol import RawFrame

from .calibrated_array import CalibratedArrayAdapter, RawArrayFrame
from .geometry import BoardCoordinateLayout
from .models import BaselineReference, StandardizationOutcome


class DoP4864StandardizationAdapter:
    """Expose the verified compact 8-bit column-major board declaration."""

    def __init__(self, layout: BoardCoordinateLayout) -> None:
        self._layout = layout
        self._adapter = CalibratedArrayAdapter(
            layout,
            adapter_version="do-p4864-observed-compact-8bit/1",
            source_schema_version="do-p4864-decoded-raw-frame/1",
        )

    @classmethod
    def observed_compact_8bit(cls) -> DoP4864StandardizationAdapter:
        return cls(
            BoardCoordinateLayout.top_left_grid(
                rows=48,
                columns=64,
                pitch_x_mm=7.99,
                pitch_y_mm=7.99,
                geometry_version="do-p4864-board-top-left-7.99mm/1",
                nominal_active_area_mm2=36.0,
            )
        )

    @property
    def layout(self) -> BoardCoordinateLayout:
        return self._layout

    def standardize(
        self,
        session_id: str,
        raw_frames: tuple[RawFrame, ...],
        *,
        baseline_reference: BaselineReference | None = None,
    ) -> StandardizationOutcome:
        decoded_frames: list[RawArrayFrame] = []
        for frame in raw_frames:
            if frame.values.shape != (48, 64) or frame.values.dtype != np.uint8:
                raise ValueError("DO-P4864 adapter requires decoded 48x64 uint8 frames")
            decoded_frames.append(
                RawArrayFrame(
                    host_monotonic_ns=frame.host_monotonic_ns,
                    values=tuple(int(value) for value in frame.values.reshape(-1, order="F")),
                    quality_flags=frame.quality_flags | frozenset({"SOURCE_INTEGRITY_UNVERIFIED"}),
                )
            )
        return self._adapter.standardize(
            session_id=session_id,
            frames=tuple(decoded_frames),
            baseline_reference=baseline_reference,
        )
