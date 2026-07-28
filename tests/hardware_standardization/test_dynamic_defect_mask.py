from __future__ import annotations

import numpy as np

from client.device.protocol import RawFrame
from client.hardware_standardization.do_p4864 import DoP4864StandardizationAdapter
from client.hardware_standardization.dynamic_defect_mask import (
    DynamicDefectEntry,
    DeviceHealthStatus,
    DynamicDefectMask,
    DynamicDefectPolicy,
    DynamicDefectStatus,
    observe_dynamic_defects,
)
from client.hardware_standardization.models import BaselineReference
from client.hardware_standardization.quality import DoP4864HardwareQualityGate, HardwareDataValidity


SHAPE = (9, 11)


def _mask() -> DynamicDefectMask:
    return DynamicDefectMask(
        device_binding_id="terminal-bound-device-1",
        mask_version=0,
        policy_version="dynamic-defect-mask/generic-grid/1",
        shape=SHAPE,
    )


def _dynamic_frames(*, failed_cells: tuple[tuple[int, int], ...] = ()) -> tuple[np.ndarray, ...]:
    frames = []
    for level in (20.0, 35.0, 55.0, 80.0, 110.0, 150.0):
        values = np.zeros(SHAPE, dtype=np.float64)
        values[2:7, 3:8] = level
        for row, column in failed_cells:
            values[row, column] = 0.0
        frames.append(values)
    return tuple(frames)


def test_dynamic_neighbour_and_temporal_evidence_promotes_only_after_two_sessions() -> None:
    failed = (4, 5)
    first = observe_dynamic_defects(
        _mask(), session_id="dynamic-1", matrices=_dynamic_frames(failed_cells=(failed,))
    )

    source_index = failed[1] * SHAPE[0] + failed[0]
    assert first.candidate_source_indices == (source_index,)
    assert first.updated_mask.entries[0].status is DynamicDefectStatus.SUSPECT
    assert not first.updated_mask.repairable_source_indices

    second = observe_dynamic_defects(
        first.updated_mask,
        session_id="dynamic-2",
        matrices=_dynamic_frames(failed_cells=(failed,)),
    )

    entry = second.updated_mask.entries[0]
    assert entry.status is DynamicDefectStatus.REPAIRABLE
    assert entry.confirmed_observations == 2
    assert second.updated_mask.repairable_source_indices == frozenset({source_index})
    assert second.updated_mask.health_status(DynamicDefectPolicy()) is DeviceHealthStatus.READY


def test_static_window_and_ordinary_dynamic_pressure_do_not_create_a_mask_entry() -> None:
    static = tuple(np.full(SHAPE, 40.0) for _ in range(6))
    no_fault = _dynamic_frames()

    static_result = observe_dynamic_defects(_mask(), session_id="static", matrices=static)
    normal_result = observe_dynamic_defects(_mask(), session_id="normal", matrices=no_fault)

    assert not static_result.candidate_source_indices
    assert not static_result.updated_mask.entries
    assert not normal_result.candidate_source_indices
    assert not normal_result.updated_mask.entries


def test_adjacent_promoted_bad_cells_make_device_unavailable_and_gate_rejects_capture() -> None:
    first = observe_dynamic_defects(
        _mask(),
        session_id="cluster-1",
        matrices=_dynamic_frames(failed_cells=((4, 5), (4, 6))),
    )
    second = observe_dynamic_defects(
        first.updated_mask,
        session_id="cluster-2",
        matrices=_dynamic_frames(failed_cells=((4, 5), (4, 6))),
    )
    assert second.updated_mask.health_status(DynamicDefectPolicy()) is DeviceHealthStatus.HEALTH_UNAVAILABLE

    adapter = DoP4864StandardizationAdapter.observed_compact_8bit()
    baseline = BaselineReference(
        schema_version="baseline-reference/1",
        baseline_window_id="baseline-dynamic-mask",
        layout_digest=adapter.layout.digest,
        zero_offset_count=(0.0,) * (48 * 64),
        noise_mad_count=(0.0,) * (48 * 64),
        rules_version="do-p4864-unloaded-baseline/1",
        threshold_version="do-p4864-quality/1",
        source_digest="a" * 64,
    )
    unusable_mask = DynamicDefectMask(
        device_binding_id="terminal-bound-device-1",
        mask_version=second.updated_mask.mask_version,
        policy_version=second.updated_mask.policy_version,
        shape=(48, 64),
        entries=(
            DynamicDefectEntry(
                source_index=100,
                status=DynamicDefectStatus.REPAIRABLE,
                confirmed_observations=2,
                last_observed_session_id="cluster-2",
            ),
            DynamicDefectEntry(
                source_index=101,
                status=DynamicDefectStatus.REPAIRABLE,
                confirmed_observations=2,
                last_observed_session_id="cluster-2",
            ),
        ),
    )
    values = np.full((48, 64), 10, dtype=np.uint8)
    values.setflags(write=False)
    frame = RawFrame(
        values=values,
        host_monotonic_ns=10,
        host_wall_time_ns=1_800_000_000_000_000_010,
        source_index=0,
        device_frame_seq=None,
        device_timestamp_ns=None,
        quality_flags=frozenset(),
    )
    result = DoP4864HardwareQualityGate(
        baseline_reference=baseline,
        dynamic_defect_mask=unusable_mask,
    ).evaluate(session_id="blocked", frames=(frame,))

    assert result.validity is HardwareDataValidity.INVALID
    assert result.reasons == ("DEVICE_DYNAMIC_DEFECT_MASK_UNUSABLE",)


def test_frozen_isolated_repairable_mask_enters_the_derived_repair_path() -> None:
    adapter = DoP4864StandardizationAdapter.observed_compact_8bit()
    baseline = BaselineReference(
        schema_version="baseline-reference/1",
        baseline_window_id="baseline-dynamic-repair",
        layout_digest=adapter.layout.digest,
        zero_offset_count=(0.0,) * (48 * 64),
        noise_mad_count=(0.0,) * (48 * 64),
        rules_version="do-p4864-unloaded-baseline/1",
        threshold_version="do-p4864-quality/1",
        source_digest="a" * 64,
    )
    source_index = 100
    mask = DynamicDefectMask(
        device_binding_id="terminal-bound-device-1",
        mask_version=2,
        policy_version="dynamic-defect-mask/generic-grid/1",
        shape=(48, 64),
        entries=(
            DynamicDefectEntry(
                source_index=source_index,
                status=DynamicDefectStatus.REPAIRABLE,
                confirmed_observations=2,
                last_observed_session_id="dynamic-2",
            ),
        ),
    )
    values = np.full((48, 64), 10, dtype=np.uint8)
    values[source_index % 48, source_index // 48] = 255
    values.setflags(write=False)
    frame = RawFrame(
        values=values,
        host_monotonic_ns=10,
        host_wall_time_ns=1_800_000_000_000_000_010,
        source_index=0,
        device_frame_seq=None,
        device_timestamp_ns=None,
        quality_flags=frozenset(),
    )

    result = DoP4864HardwareQualityGate(
        baseline_reference=baseline,
        dynamic_defect_mask=mask,
    ).evaluate(session_id="repaired", frames=(frame,))

    assert result.validity is HardwareDataValidity.VALID
    assert result.repaired_source_indices == (source_index,)
    assert result.physical_session is not None
    assert result.physical_session.frames[0].repaired_count is not None
    assert result.physical_session.frames[0].repaired_count[source_index] == 10.0
