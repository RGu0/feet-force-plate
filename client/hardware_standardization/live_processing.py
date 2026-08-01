"""One-frame DO-P4864 standardization for every live display consumer.

The serial parser owns immutable ``RawFrame`` objects.  This module produces a
separate standardized frame for display and debug analysis: explicit known-bad
regions are excluded, repairable defects are processed, the declared baseline
is applied, and the device's frozen force/geometry adapter is exercised.  It
never mutates or persists the raw matrix.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Protocol

import numpy as np

from client.device.protocol import RawFrame

from .defect_repair import SensorDefectRepairPolicy, repair_sensor_defects
from .do_p4864 import DoP4864StandardizationAdapter
from .models import BaselineReference, StandardizationStatus
from .ports import DecodedHardwareFrame


class FrameStandardizationError(ValueError):
    """A frame cannot safely enter display or local-analysis processing."""


class FrameStandardizer(Protocol):
    """Maps immutable decoded frames to immutable standardized derivatives."""

    def standardize(self, frame: DecodedHardwareFrame) -> DecodedHardwareFrame: ...


@dataclass(frozen=True, slots=True)
class DoP4864LiveProcessingProfile:
    """Explicit configuration shared by replay and a real DO-P4864 adapter."""

    version: str
    baseline_reference: BaselineReference
    known_excluded_cells: frozenset[tuple[int, int]] = frozenset()
    defect_repair_policy: SensorDefectRepairPolicy = SensorDefectRepairPolicy()

    def __post_init__(self) -> None:
        if not self.version:
            raise ValueError("live processing profile version is required")


class DoP4864LiveFrameStandardizer:
    """Run the declared DO-P4864 path before a frame reaches UI or analysis."""

    def __init__(
        self,
        profile: DoP4864LiveProcessingProfile,
        *,
        adapter: DoP4864StandardizationAdapter | None = None,
    ) -> None:
        self._profile = profile
        self._adapter = adapter or DoP4864StandardizationAdapter.observed_compact_8bit()
        if profile.baseline_reference.layout_digest != self._adapter.layout.digest:
            raise ValueError("live processing baseline does not match the DO-P4864 layout")

    @property
    def profile_version(self) -> str:
        return self._profile.version

    def standardize(self, frame: RawFrame) -> RawFrame:
        values = np.asarray(frame.values)
        if values.shape != (48, 64) or values.dtype != np.uint8:
            raise FrameStandardizationError("DO-P4864 实时帧不符合 48×64 uint8 标准")
        repair = repair_sensor_defects(
            (values,),
            known_excluded_cells=self._profile.known_excluded_cells,
            policy=self._profile.defect_repair_policy,
        )
        if not repair.valid:
            raise FrameStandardizationError("传感器坏点处理未通过：" + ", ".join(repair.reasons))
        outcome = self._adapter.standardize(
            session_id=f"live-{frame.source_index}",
            raw_frames=(frame,),
            baseline_reference=self._profile.baseline_reference,
            processing_matrices=(repair.frames[0].values,),
        )
        if outcome.status is StandardizationStatus.INVALID or outcome.session is None:
            raise FrameStandardizationError("硬件标准化未生成可用显示帧")
        physical = outcome.session.frames[0]
        if physical.relative_load_count is None:
            raise FrameStandardizationError("硬件标准化缺少零点校正相对载荷")
        standardized = np.asarray(physical.relative_load_count, dtype=np.float64).reshape(
            (48, 64), order="F"
        )
        standardized.setflags(write=False)
        flags = set(frame.quality_flags)
        flags.update(physical.quality_flags)
        flags.add("HARDWARE_STANDARDIZED")
        flags.add(f"LIVE_PROCESSING_PROFILE:{self._profile.version}")
        if self._profile.known_excluded_cells:
            flags.add("BAD_CELL_EXCLUDED")
        return replace(frame, values=standardized, quality_flags=frozenset(flags))


def replay_debug_profile(*, fixture_sha256: str) -> DoP4864LiveProcessingProfile:
    """The only baseline permitted for a relative, de-identified replay input.

    The fixture has no unloaded capture or physical calibration evidence.  A
    declared all-zero reference therefore preserves its relative-count nature
    while still exercising the same zero-reference/geometry/force adapter path.
    This profile is never a substitute for a real-device unloaded baseline.
    """

    adapter = DoP4864StandardizationAdapter.observed_compact_8bit()
    width = 48 * 64
    baseline = BaselineReference(
        schema_version="baseline-reference/1",
        baseline_window_id="replay-debug-relative-zero/1",
        layout_digest=adapter.layout.digest,
        zero_offset_count=(0.0,) * width,
        noise_mad_count=(0.0,) * width,
        rules_version="replay-debug-relative-zero/1",
        threshold_version="replay-debug-relative-zero/1",
        source_digest=fixture_sha256,
    )
    # Captured engineering evidence identifies this rectangle as a persistent
    # non-anatomical response in the approved replay fixture.  Exclusion is
    # explicit, versioned, and applied before every display/analysis frame.
    excluded = frozenset(
        (row, column) for row in range(16, 24) for column in range(39, 48)
    )
    return DoP4864LiveProcessingProfile(
        version="do-p4864/replay-debug-standardization/1",
        baseline_reference=baseline,
        known_excluded_cells=excluded,
    )
