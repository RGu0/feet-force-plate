from __future__ import annotations

import pytest

from client.device.stage_windows import (
    CapturedStageWindow,
    validate_captured_stage_windows,
)
from client.workflow.protocol import default_standard_protocol


def _expected_stage_ids() -> tuple[str, ...]:
    return tuple(stage.stage_id for stage in default_standard_protocol().stages)


def test_captured_windows_allow_preparation_gaps_but_require_protocol_order() -> None:
    windows = (
        CapturedStageWindow("BILATERAL_EYES_OPEN", 0.0, 20.0, 600),
        CapturedStageWindow("BILATERAL_EYES_CLOSED", 34.5, 54.5, 601),
        CapturedStageWindow("SEMI_TANDEM_LEFT_FORWARD", 70.0, 90.0, 599),
        CapturedStageWindow("SEMI_TANDEM_RIGHT_FORWARD", 105.0, 125.0, 602),
    )

    assert validate_captured_stage_windows(
        windows,
        expected_stage_ids=_expected_stage_ids(),
        minimum_duration_s=20.0,
    ) == windows


@pytest.mark.parametrize(
    "windows",
    (
        (),
        (
            CapturedStageWindow("BILATERAL_EYES_OPEN", 0.0, 20.0, 600),
            CapturedStageWindow("BILATERAL_EYES_OPEN", 34.5, 54.5, 601),
            CapturedStageWindow("SEMI_TANDEM_LEFT_FORWARD", 70.0, 90.0, 599),
            CapturedStageWindow("SEMI_TANDEM_RIGHT_FORWARD", 105.0, 125.0, 602),
        ),
        (
            CapturedStageWindow("BILATERAL_EYES_CLOSED", 0.0, 20.0, 600),
            CapturedStageWindow("BILATERAL_EYES_OPEN", 34.5, 54.5, 601),
            CapturedStageWindow("SEMI_TANDEM_LEFT_FORWARD", 70.0, 90.0, 599),
            CapturedStageWindow("SEMI_TANDEM_RIGHT_FORWARD", 105.0, 125.0, 602),
        ),
        (
            CapturedStageWindow("BILATERAL_EYES_OPEN", 0.0, 20.0, 600),
            CapturedStageWindow("BILATERAL_EYES_CLOSED", 19.5, 39.5, 601),
            CapturedStageWindow("SEMI_TANDEM_LEFT_FORWARD", 70.0, 90.0, 599),
            CapturedStageWindow("SEMI_TANDEM_RIGHT_FORWARD", 105.0, 125.0, 602),
        ),
        (
            CapturedStageWindow("BILATERAL_EYES_OPEN", 0.0, 20.0, 600),
            CapturedStageWindow("BILATERAL_EYES_CLOSED", 34.5, 54.49, 601),
            CapturedStageWindow("SEMI_TANDEM_LEFT_FORWARD", 70.0, 90.0, 599),
            CapturedStageWindow("SEMI_TANDEM_RIGHT_FORWARD", 105.0, 125.0, 602),
        ),
    ),
)
def test_captured_windows_reject_missing_duplicate_reordered_overlapping_or_short_stages(
    windows: tuple[CapturedStageWindow, ...],
) -> None:
    with pytest.raises(ValueError, match="captured stage windows"):
        validate_captured_stage_windows(
            windows,
            expected_stage_ids=_expected_stage_ids(),
            minimum_duration_s=20.0,
        )


@pytest.mark.parametrize(
    "stage_id,start_s,end_s,frame_count",
    (
        ("", 0.0, 20.0, 1),
        ("BILATERAL_EYES_OPEN", -0.1, 20.0, 1),
        ("BILATERAL_EYES_OPEN", 20.0, 20.0, 1),
        ("BILATERAL_EYES_OPEN", 0.0, 20.0, 0),
    ),
)
def test_captured_stage_window_rejects_invalid_timing_or_frames(
    stage_id: str, start_s: float, end_s: float, frame_count: int
) -> None:
    with pytest.raises(ValueError):
        CapturedStageWindow(stage_id, start_s, end_s, frame_count)
