from __future__ import annotations

import json

import numpy as np
import pytest

from client.device.protocol import RawFrame
from client.hardware_standardization.do_p4864 import DoP4864StandardizationAdapter
from client.hardware_standardization.models import BaselineReference
from client.hardware_standardization.public_export import (
    PublicPressureExportError,
    export_committed_valid_hardware_session,
)
from client.hardware_standardization.quality import (
    BadPointPolicy,
    DoP4864HardwareQualityGate,
)


def _baseline() -> BaselineReference:
    adapter = DoP4864StandardizationAdapter.observed_compact_8bit()
    return BaselineReference(
        schema_version="baseline-reference/1",
        baseline_window_id="baseline-public-export",
        layout_digest=adapter.layout.digest,
        zero_offset_count=(0.0,) * (48 * 64),
        noise_mad_count=(0.0,) * (48 * 64),
        rules_version="do-p4864-unloaded-baseline/1",
        threshold_version="do-p4864-quality/1",
        source_digest="a" * 64,
    )


def _frame(value: int, *, timestamp_ns: int, source_index: int) -> RawFrame:
    values = np.full((48, 64), value, dtype=np.uint8)
    values.setflags(write=False)
    return RawFrame(
        values=values,
        host_monotonic_ns=timestamp_ns,
        host_wall_time_ns=1_800_000_000_000_000_000 + timestamp_ns,
        source_index=source_index,
        device_frame_seq=None,
        device_timestamp_ns=None,
        quality_flags=frozenset({"CHECKSUM_NOT_ENFORCED"}),
    )


def _valid_evaluation():
    return DoP4864HardwareQualityGate(baseline_reference=_baseline()).evaluate(
        session_id="public-session",
        frames=(
            _frame(10, timestamp_ns=10_000_000, source_index=0),
            _frame(11, timestamp_ns=58_380_000, source_index=1),
        ),
    )


def test_public_export_contains_only_device_independent_force_fields() -> None:
    evaluation = _valid_evaluation()

    exported = export_committed_valid_hardware_session(
        evaluation, local_session_committed=True
    )
    payload = exported.to_dict()

    assert set(payload) == {
        "schema_version",
        "session_id",
        "coordinate_frame",
        "coordinate_unit",
        "force_unit",
        "time_unit",
        "points",
        "frames",
    }
    assert payload["schema_version"] == "physical-pressure-session/1.0"
    assert payload["points"][0] == {
        "point_id": "point-0001",
        "board_x_mm": 0.0,
        "board_y_mm": 0.0,
    }
    assert payload["points"][1]["point_id"] == "point-0002"
    assert payload["points"][1]["board_x_mm"] == 0.0
    assert payload["points"][1]["board_y_mm"] == 7.99
    assert payload["frames"][1]["timestamp_s"] == pytest.approx(0.04838)
    assert len(payload["points"]) == len(payload["frames"][0]["normal_force_n"]) == 3072
    assert all(value >= 0 for value in payload["frames"][0]["normal_force_n"])
    serialized = json.dumps(payload, sort_keys=True, allow_nan=False)
    for private_field in (
        "raw_count",
        "source_index",
        "quality_flags",
        "estimated_force_n",
        "repaired_count",
        "checksum",
        "protocol",
    ):
        assert private_field not in serialized


def test_public_export_requires_valid_and_committed_hardware_result() -> None:
    valid = _valid_evaluation()
    with pytest.raises(PublicPressureExportError, match="committed"):
        export_committed_valid_hardware_session(valid, local_session_committed=False)

    invalid = DoP4864HardwareQualityGate(
        baseline_reference=_baseline(),
        policy=BadPointPolicy(known_bad_source_indices=frozenset({100, 101})),
    ).evaluate(
        session_id="invalid-session",
        frames=(_frame(10, timestamp_ns=10, source_index=0),),
    )
    assert invalid.validity.value == "INVALID"
    with pytest.raises(PublicPressureExportError, match="invalid hardware"):
        export_committed_valid_hardware_session(invalid, local_session_committed=True)
