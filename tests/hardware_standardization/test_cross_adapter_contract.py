from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from client.device.protocol import RawFrame
from client.hardware_standardization.calibrated_array import CalibratedArrayAdapter, RawArrayFrame
from client.hardware_standardization.do_p4864 import DoP4864StandardizationAdapter


FIXTURE = Path("tests/fixtures/hardware_standardization/contract-cases.json")


def test_contract_fixture_covers_irregular_quality_and_nonuniform_time_cases() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    case_names = {case["name"] for case in payload["cases"]}

    assert payload["fixture_schema_version"] == "physical-array-contract-cases/1"
    assert {"irregular-mirrored-layout", "quality-conditions", "nonuniform-baseline-time"} <= case_names


def test_do_adapter_and_generic_adapter_agree_on_the_same_board_point_order() -> None:
    values = np.arange(48 * 64, dtype=np.uint16).reshape((48, 64), order="F").astype(np.uint8)
    values.setflags(write=False)
    raw = RawFrame(
        values=values,
        host_monotonic_ns=50_000_000,
        host_wall_time_ns=1_800_000_000_050_000_000,
        source_index=0,
        device_frame_seq=None,
        device_timestamp_ns=None,
        quality_flags=frozenset(),
    )
    do_adapter = DoP4864StandardizationAdapter.observed_compact_8bit()
    generic_adapter = CalibratedArrayAdapter(do_adapter.layout)

    do_outcome = do_adapter.standardize("do-session", (raw,))
    generic_outcome = generic_adapter.standardize(
        session_id="generic-session",
        frames=(RawArrayFrame(raw.host_monotonic_ns, tuple(values.reshape(-1, order="F")), frozenset()),),
    )

    assert do_outcome.session is not None
    assert generic_outcome.session is not None
    assert do_outcome.session.cells == generic_outcome.session.cells
    assert do_outcome.session.frames[0].raw_count == generic_outcome.session.frames[0].raw_count
