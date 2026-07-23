from __future__ import annotations

import numpy as np

from client.device.protocol import RawFrame
from client.hardware_standardization.do_p4864 import DoP4864StandardizationAdapter
from client.hardware_standardization.models import BaselineReference
from client.hardware_standardization.quality import (
    BadPointPolicy,
    DoP4864HardwareQualityGate,
    HardwareDataValidity,
)


def _baseline(*, noisy: dict[int, float] | None = None) -> BaselineReference:
    adapter = DoP4864StandardizationAdapter.observed_compact_8bit()
    mad = [0.0] * (48 * 64)
    for source_index, value in (noisy or {}).items():
        mad[source_index] = value
    return BaselineReference(
        schema_version="baseline-reference/1",
        baseline_window_id="baseline-1",
        layout_digest=adapter.layout.digest,
        zero_offset_count=(0.0,) * (48 * 64),
        noise_mad_count=tuple(mad),
        rules_version="do-p4864-unloaded-baseline/1",
        threshold_version="do-p4864-quality/1",
        source_digest="a" * 64,
    )


def _frame(values: np.ndarray, *, timestamp_ns: int, source_index: int) -> RawFrame:
    immutable = np.asarray(values, dtype=np.uint8).copy()
    immutable.setflags(write=False)
    return RawFrame(
        values=immutable,
        host_monotonic_ns=timestamp_ns,
        host_wall_time_ns=1_800_000_000_000_000_000 + timestamp_ns,
        source_index=source_index,
        device_frame_seq=None,
        device_timestamp_ns=None,
        quality_flags=frozenset({"CHECKSUM_NOT_ENFORCED"}),
    )


def test_quality_gate_preserves_raw_and_emits_v1_estimated_force() -> None:
    values = np.full((48, 64), 10, dtype=np.uint8)
    gate = DoP4864HardwareQualityGate(baseline_reference=_baseline())

    result = gate.evaluate(
        session_id="session-1",
        frames=(_frame(values, timestamp_ns=10, source_index=0), _frame(values, timestamp_ns=20, source_index=1)),
    )

    assert result.validity is HardwareDataValidity.VALID
    assert result.physical_session is not None
    output = result.physical_session.frames[0]
    assert output.raw_count[0] == 10
    assert output.repaired_count is None
    assert output.estimated_force_n is not None
    assert output.estimated_force_n[0] > 0
    assert "ESTIMATED_FORCE_V1" in output.quality_flags


def test_isolated_bad_cell_is_repaired_from_four_orthogonal_neighbours() -> None:
    source_index = 100
    row, column = source_index % 48, source_index // 48
    values = np.full((48, 64), 10, dtype=np.uint8)
    values[row, column] = 255
    gate = DoP4864HardwareQualityGate(
        baseline_reference=_baseline(),
        policy=BadPointPolicy(known_bad_source_indices=frozenset({source_index})),
    )

    result = gate.evaluate(
        session_id="session-2",
        frames=(_frame(values, timestamp_ns=10, source_index=0), _frame(values, timestamp_ns=20, source_index=1)),
    )

    assert result.validity is HardwareDataValidity.VALID
    assert result.repaired_source_indices == (source_index,)
    assert result.physical_session is not None
    output = result.physical_session.frames[0]
    assert output.raw_count[source_index] == 255
    assert output.repaired_count is not None
    assert output.repaired_count[source_index] == 10.0
    assert output.repaired_cell_mask is not None
    assert output.repaired_cell_mask[source_index]
    assert output.estimated_force_n is not None
    assert output.estimated_force_n[source_index] > 0


def test_adjacent_or_saturated_bad_cells_invalidate_the_whole_capture() -> None:
    values = np.full((48, 64), 10, dtype=np.uint8)
    clustered = DoP4864HardwareQualityGate(
        baseline_reference=_baseline(),
        policy=BadPointPolicy(known_bad_source_indices=frozenset({100, 101})),
    ).evaluate(
        session_id="cluster",
        frames=(_frame(values, timestamp_ns=10, source_index=0), _frame(values, timestamp_ns=20, source_index=1)),
    )
    values[4, 2] = 255
    saturated = DoP4864HardwareQualityGate(baseline_reference=_baseline()).evaluate(
        session_id="saturated",
        frames=(_frame(values, timestamp_ns=10, source_index=0), _frame(values, timestamp_ns=20, source_index=1)),
    )

    assert clustered.validity is HardwareDataValidity.INVALID
    assert clustered.reasons == ("ADJACENT_BAD_CELL_CLUSTER",)
    assert saturated.validity is HardwareDataValidity.INVALID
    assert saturated.reasons == ("FORCE_CONVERSION_OR_SATURATION_FAILED",)
