from __future__ import annotations

import numpy as np
import pytest

from client.device.protocol import RawFrame
from client.hardware_standardization.do_p4864 import DoP4864StandardizationAdapter
from client.hardware_standardization.models import StandardizationStatus


def _raw_frame(values: np.ndarray, timestamp_ns: int) -> RawFrame:
    immutable = np.asarray(values, dtype=np.uint8).copy()
    immutable.setflags(write=False)
    return RawFrame(
        values=immutable,
        host_monotonic_ns=timestamp_ns,
        host_wall_time_ns=1_800_000_000_000_000_000 + timestamp_ns,
        source_index=0,
        device_frame_seq=None,
        device_timestamp_ns=None,
        quality_flags=frozenset({"CHECKSUM_NOT_ENFORCED", "COMPACT_8BIT_PAYLOAD_UNVERIFIED"}),
    )


def test_do_adapter_uses_confirmed_board_grid_and_preserves_raw_matrix() -> None:
    values = np.arange(48 * 64, dtype=np.uint16).reshape((48, 64), order="F").astype(np.uint8)
    frame = _raw_frame(values, 20_000_000)
    original = frame.values.copy()
    adapter = DoP4864StandardizationAdapter.observed_compact_8bit()

    outcome = adapter.standardize("session-1", (frame,))

    assert outcome.status is StandardizationStatus.DEGRADED
    assert outcome.session is not None
    assert outcome.session.coordinate_frame == "BOARD_TOP_LEFT_X_RIGHT_Y_DOWN"
    assert outcome.session.cells[0].board_x_mm == 0.0
    assert outcome.session.cells[0].board_y_mm == 0.0
    assert outcome.session.cells[99].board_x_mm == pytest.approx(15.98)
    assert outcome.session.cells[99].board_y_mm == pytest.approx(23.97)
    assert outcome.session.frames[0].raw_count == tuple(values.reshape(-1, order="F"))
    assert outcome.session.frames[0].estimated_force_n is None
    assert "CHECKSUM_NOT_ENFORCED" in outcome.session.frames[0].quality_flags
    assert np.array_equal(frame.values, original)
    assert not frame.values.flags.writeable
