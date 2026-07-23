from __future__ import annotations

import json

from client.hardware_standardization.calibrated_array import CalibratedArrayAdapter, RawArrayFrame
from client.hardware_standardization.geometry import BoardCoordinateLayout
from client.hardware_standardization.serialization import physical_array_session_to_dict


def test_serialization_emits_board_coordinates_and_null_force_without_body_fields() -> None:
    layout = BoardCoordinateLayout.top_left_grid(
        rows=1,
        columns=2,
        pitch_x_mm=7.99,
        pitch_y_mm=7.99,
        geometry_version="fixture/1",
        nominal_active_area_mm2=36.0,
    )
    outcome = CalibratedArrayAdapter(layout).standardize(
        session_id="session-1",
        frames=(RawArrayFrame(0, (4, 8), frozenset()),),
    )

    assert outcome.session is not None
    payload = physical_array_session_to_dict(outcome.session)

    assert payload["schema_version"] == "physical-sensor-observation/1.0"
    assert payload["coordinate_frame"] == "BOARD_TOP_LEFT_X_RIGHT_Y_DOWN"
    assert payload["cells"][1]["board_x_mm"] == 7.99
    assert payload["frames"][0]["normal_force_n"] == [None, None]
    assert "ml_mm" not in json.dumps(payload)
    assert "ap_mm" not in json.dumps(payload)
    assert json.dumps(payload, sort_keys=True, allow_nan=False)
