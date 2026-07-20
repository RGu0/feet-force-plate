from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest

from client.local_analysis.display import (
    DisplayRefreshController,
    LatestDisplayFrameMailbox,
    build_display_frame,
)


def _counts(left: float = 1000.0, right: float = 1000.0) -> np.ndarray:
    counts = np.zeros((48, 64), dtype=np.float64)
    counts[20, 10] = left
    counts[20, 53] = right
    return counts


def test_display_frame_is_immutable_48x64_and_has_cop_and_text_metrics() -> None:
    source = _counts(1500.0, 500.0)

    frame = build_display_frame(
        source,
        sequence=7,
        captured_monotonic_seconds=12.5,
        cop_trail=(),
        total_trend=(),
    )
    source[20, 10] = 0

    assert len(frame.relative_heatmap) == 48
    assert len(frame.relative_heatmap[0]) == 64
    assert frame.relative_heatmap[20][10] == 1.0
    assert frame.cop_x == pytest.approx(20.75)
    assert frame.cop_y == pytest.approx(20.0)
    assert frame.left_load_percent == pytest.approx(75.0)
    assert frame.right_load_percent == pytest.approx(25.0)
    assert frame.total_relative_load == pytest.approx(2000.0)
    assert frame.sequence == 7
    assert frame.captured_monotonic_seconds == 12.5


def test_latest_only_mailbox_drops_old_display_frames_without_touching_reliable_sink() -> None:
    mailbox = LatestDisplayFrameMailbox()
    reliably_stored_sequences: list[int] = []
    for sequence in range(3):
        reliably_stored_sequences.append(sequence)
        mailbox.publish(
            build_display_frame(
                _counts(),
                sequence=sequence,
                captured_monotonic_seconds=float(sequence),
                cop_trail=(),
                total_trend=(),
            )
        )

    latest = mailbox.take_latest(after_sequence=-1)

    assert latest.sequence == 2
    assert mailbox.take_latest(after_sequence=2) is None
    assert reliably_stored_sequences == [0, 1, 2]


def test_refresh_throttle_returns_only_new_device_frames_and_keeps_capture_timestamp() -> None:
    mailbox = LatestDisplayFrameMailbox()
    refresh = DisplayRefreshController(mailbox, maximum_refresh_hz=30.0)
    mailbox.publish(
        build_display_frame(
            _counts(),
            sequence=1,
            captured_monotonic_seconds=1.0,
            cop_trail=(),
            total_trend=(),
        )
    )

    first = refresh.poll(now_monotonic_seconds=0.0)
    too_soon = refresh.poll(now_monotonic_seconds=0.01)
    mailbox.publish(
        build_display_frame(
            _counts(),
            sequence=2,
            captured_monotonic_seconds=1.083,
            cop_trail=first.cop_trail,
            total_trend=first.total_trend,
        )
    )
    second = refresh.poll(now_monotonic_seconds=0.034)

    assert first.sequence == 1
    assert too_soon is None
    assert second.sequence == 2
    assert second.captured_monotonic_seconds == 1.083
    assert refresh.last_sequence == 2


def test_mailbox_is_thread_safe_under_stalled_ui_consumer() -> None:
    mailbox = LatestDisplayFrameMailbox()

    def publish(sequence: int) -> None:
        mailbox.publish(
            build_display_frame(
                _counts(),
                sequence=sequence,
                captured_monotonic_seconds=sequence / 12.0,
                cop_trail=(),
                total_trend=(),
            )
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(publish, range(100)))

    latest = mailbox.take_latest(after_sequence=-1)
    assert latest.sequence == 99
