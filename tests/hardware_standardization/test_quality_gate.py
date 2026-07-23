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


def test_two_isolated_bad_cells_are_repaired_but_edge_or_unstable_baseline_is_rejected() -> None:
    values = np.full((48, 64), 10, dtype=np.uint8)
    first, second = 100, 700
    for source_index in (first, second):
        values[source_index % 48, source_index // 48] = 255
    frames = (
        _frame(values, timestamp_ns=10, source_index=0),
        _frame(values, timestamp_ns=20, source_index=1),
    )
    repaired = DoP4864HardwareQualityGate(
        baseline_reference=_baseline(),
        policy=BadPointPolicy(known_bad_source_indices=frozenset({first, second})),
    ).evaluate(session_id="two-isolated", frames=frames)
    edge = DoP4864HardwareQualityGate(
        baseline_reference=_baseline(),
        policy=BadPointPolicy(known_bad_source_indices=frozenset({0})),
    ).evaluate(session_id="edge", frames=frames)
    unstable = DoP4864HardwareQualityGate(
        baseline_reference=_baseline(noisy={100: 2.0, 700: 2.0, 1300: 2.0})
    ).evaluate(session_id="unstable", frames=frames)

    assert repaired.validity is HardwareDataValidity.VALID
    assert repaired.repaired_source_indices == (first, second)
    assert edge.validity is HardwareDataValidity.INVALID
    assert edge.reasons == ("BAD_CELL_CANNOT_BE_REPAIRED_AT_BOARD_EDGE",)
    assert unstable.validity is HardwareDataValidity.INVALID
    assert unstable.reasons == ("TOO_MANY_PERSISTENT_BAD_CELLS",)


def test_persistent_horizontal_line_is_repaired_before_standardization_with_audit_metadata() -> None:
    values = np.full((48, 64), 10, dtype=np.uint8)
    values[20, :] = 0
    raw_before = values.copy()
    result = DoP4864HardwareQualityGate(baseline_reference=_baseline()).evaluate(
        session_id="line-repair",
        frames=(
            _frame(values, timestamp_ns=10, source_index=0),
            _frame(values, timestamp_ns=20, source_index=1),
            _frame(values, timestamp_ns=30, source_index=2),
        ),
    )

    assert result.validity is HardwareDataValidity.VALID
    assert result.physical_session is not None
    output = result.physical_session.frames[0]
    assert output.raw_count[20] == 0
    assert output.repaired_count is not None
    assert output.repaired_count[20] == 10.0
    assert output.repaired_cell_mask is not None
    assert output.repaired_cell_mask[20]
    assert output.relative_load_count is not None
    assert output.relative_load_count[20] == 10.0
    assert len(result.repaired_source_indices) == 64
    assert result.processing_metadata is not None
    repair = result.processing_metadata["sensor_defect_repair"]
    assert repair["persistent_missing_rows"] == [20]
    assert repair["persistent_missing_columns"] == []
    assert (
        repair["method_counts"]["HORIZONTAL_LINE_DIRECTIONAL_INTERPOLATION"]
        == 192
    )
    assert np.array_equal(values, raw_before)
