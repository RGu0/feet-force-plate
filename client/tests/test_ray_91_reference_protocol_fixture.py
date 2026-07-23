from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from client.app.live_display import LiveDisplayProjection
from client.device.acquisition import LatestFrameMailbox
from client.device.protocol import RawFrame
from client.local_analysis.display import LatestDisplayFrameMailbox


FIXTURE_DIRECTORY = (
    Path(__file__).resolve().parents[2]
    / "tests/fixtures/device/dop4864_reference_protocol_v1"
)
FIXTURE = FIXTURE_DIRECTORY / "reference-poses.npz"
METADATA = FIXTURE_DIRECTORY / "metadata.json"
COMPATIBILITY_MIRROR = (
    Path(__file__).parent / "fixtures" / "dop4864_reference_protocol_v1" / "reference-poses.npz"
)
POSES = (
    "open_eyes_bilateral",
    "closed_eyes_bilateral",
    "tandem_left_front",
    "tandem_right_front",
)


def test_reference_protocol_fixture_has_all_deidentified_20_second_pose_sequences() -> None:
    metadata = json.loads(METADATA.read_text(encoding="utf-8"))
    assert metadata["schema_version"] == "do-p4864-reference-protocol/1"
    assert metadata["canonical_fixture_path"] == (
        "tests/fixtures/device/dop4864_reference_protocol_v1/reference-poses.npz"
    )
    assert metadata["nominal_frame_interval_ms"] == 50
    assert metadata["deidentification"]["retained"] == "per-pose relative 48x64 matrix sequence only"
    assert "serial bytes" in metadata["deidentification"]["removed"]
    assert set(metadata["poses"]) == set(POSES)
    with np.load(FIXTURE, allow_pickle=False) as fixture:
        assert str(fixture["schema_version"]) == metadata["schema_version"]
        assert int(fixture["nominal_frame_interval_ms"]) == 50
        for pose in POSES:
            values = fixture[pose]
            assert values.dtype == np.uint8
            assert values.ndim == 3
            assert values.shape[1:] == (48, 64)
            assert values.shape[0] >= 400
            assert values.max() > 0
            assert values.min() >= 0
            assert metadata["poses"][pose]["frames"] == values.shape[0]


def test_compatibility_mirror_matches_the_canonical_test_fixture() -> None:
    assert FIXTURE.is_file()
    assert COMPATIBILITY_MIRROR.is_file()
    assert hashlib.sha256(FIXTURE.read_bytes()).hexdigest() == hashlib.sha256(
        COMPATIBILITY_MIRROR.read_bytes()
    ).hexdigest()


@pytest.mark.parametrize("pose", POSES)
def test_reference_protocol_fixture_is_repeatable_relative_input(pose: str) -> None:
    with np.load(FIXTURE, allow_pickle=False) as fixture:
        values = fixture[pose]
        copied = values.copy()
        normalized = values.astype(np.float64) / 255.0

    assert np.array_equal(values, copied)
    assert np.all((normalized >= 0.0) & (normalized <= 1.0))


@pytest.mark.parametrize("pose", POSES)
def test_reference_protocol_replays_through_the_production_display_projection(pose: str) -> None:
    """Use the saved reference before requiring another physical-device run."""
    with np.load(FIXTURE, allow_pickle=False) as fixture:
        source_values = fixture[pose]
        source_before = source_values.copy()

    raw_mailbox = LatestFrameMailbox()
    display_mailbox = LatestDisplayFrameMailbox()
    projection = LiveDisplayProjection(source=raw_mailbox, destination=display_mailbox)
    for source_index, values in enumerate(source_values):
        immutable_values = values.copy()
        immutable_values.setflags(write=False)
        raw_mailbox.publish(
            RawFrame(
                values=immutable_values,
                host_monotonic_ns=source_index * 50_000_000,
                host_wall_time_ns=source_index * 50_000_000,
                source_index=source_index,
                device_frame_seq=None,
                device_timestamp_ns=None,
                quality_flags=frozenset({"REFERENCE_FIXTURE"}),
            )
        )
        displayed = projection.poll()
        assert displayed is not None
        assert displayed.sequence == source_index
        assert displayed.cop_x is not None
        assert displayed.cop_y is not None
        assert displayed.total_relative_load > 0

    latest = display_mailbox.take_latest(after_sequence=-1)
    assert latest is not None
    assert latest.sequence == len(source_values) - 1
    assert len(latest.relative_heatmap) == 48
    assert len(latest.relative_heatmap[0]) == 64
    assert np.array_equal(source_values, source_before)
