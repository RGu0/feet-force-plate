from __future__ import annotations

import numpy as np

from client.app.fixture_replay import FixtureReplaySource, StandardizedReplaySource
from client.app.live_display import LiveDisplayProjection
from client.device.acquisition import LatestFrameMailbox
from client.hardware_standardization.live_processing import (
    DoP4864LiveFrameStandardizer,
    replay_debug_profile,
)
from client.local_analysis.display import LatestDisplayFrameMailbox


def _standardizer(source: FixtureReplaySource) -> DoP4864LiveFrameStandardizer:
    return DoP4864LiveFrameStandardizer(
        replay_debug_profile(fixture_sha256=source.fixture_sha256)
    )


def test_replay_processing_excludes_declared_bad_region_without_mutating_raw_fixture() -> None:
    source = FixtureReplaySource.from_repository()
    raw = next(source.frames_for("BILATERAL_EYES_OPEN"))
    raw_before = raw.values.copy()

    standardized = _standardizer(source).standardize(raw)

    assert np.array_equal(raw.values, raw_before)
    assert not raw.values.flags.writeable
    assert not standardized.values.flags.writeable
    assert np.all(standardized.values[16:24, 39:48] == 0.0)
    assert "HARDWARE_STANDARDIZED" in standardized.quality_flags
    assert "ZERO_OFFSET_APPLIED" in standardized.quality_flags
    assert "BAD_CELL_EXCLUDED" in standardized.quality_flags


def test_replay_display_and_analysis_source_share_the_same_standardized_input() -> None:
    source = FixtureReplaySource.from_repository()
    standardizer = _standardizer(source)
    raw = next(source.frames_for("BILATERAL_EYES_OPEN"))
    analysis_frame = next(
        StandardizedReplaySource(source, standardizer).frames_for("BILATERAL_EYES_OPEN")
    )
    raw_mailbox = LatestFrameMailbox()
    display_mailbox = LatestDisplayFrameMailbox()
    projection = LiveDisplayProjection(
        source=raw_mailbox,
        destination=display_mailbox,
        standardizer=standardizer,
    )
    raw_mailbox.publish(raw)

    display = projection.poll()

    assert display is not None
    assert np.all(np.asarray(analysis_frame.values)[16:24, 39:48] == 0.0)
    assert np.all(np.asarray(display.relative_heatmap)[16:24, 39:48] == 0.0)
    assert display.total_relative_load == float(np.asarray(analysis_frame.values).sum())
