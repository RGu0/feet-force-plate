"""Thin DO-P4864 adapter over decoded RawFrame values; never a byte parser."""

from __future__ import annotations

import numpy as np
from pathlib import Path

from client.device.protocol import RawFrame

from .calibrated_array import CalibratedArrayAdapter, RawArrayFrame
from .device_specification import DeviceSpecification, load_device_specification
from .geometry import BoardCoordinateLayout
from .models import BaselineReference, StandardizationOutcome


class DoP4864StandardizationAdapter:
    """Expose the verified compact 8-bit column-major board declaration."""

    def __init__(self, specification: DeviceSpecification) -> None:
        if not specification.specification_id.startswith("do-p4864/"):
            raise ValueError("DO-P4864 adapter requires the DO-P4864 device specification")
        self._specification = specification
        self._layout = specification.layout
        self._adapter = specification.make_adapter()

    @classmethod
    def observed_compact_8bit(cls) -> DoP4864StandardizationAdapter:
        specification_path = (
            Path(__file__).resolve().parents[2]
            / "docs/hardware/device-specifications/do-p4864/1.0.json"
        )
        return cls(load_device_specification(specification_path))

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
            expected_dtype = np.dtype(self._specification.decoded_value_dtype)
            if (
                frame.values.shape != self._specification.matrix_shape
                or frame.values.dtype != expected_dtype
            ):
                raise ValueError(
                    "DO-P4864 adapter requires frames matching its device specification"
                )
            flatten_order = {
                "COLUMN_MAJOR": "F",
                "ROW_MAJOR": "C",
            }[self._specification.payload_value_order]
            decoded_frames.append(
                RawArrayFrame(
                    host_monotonic_ns=frame.host_monotonic_ns,
                    values=tuple(
                        int(value) for value in frame.values.reshape(-1, order=flatten_order)
                    ),
                    quality_flags=frame.quality_flags | frozenset({"SOURCE_INTEGRITY_UNVERIFIED"}),
                )
            )
        return self._adapter.standardize(
            session_id=session_id,
            frames=tuple(decoded_frames),
            baseline_reference=baseline_reference,
        )
