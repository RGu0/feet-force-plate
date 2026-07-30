from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from client.device.protocol import RawFrame
from client.device.session_replay import (
    InternalSessionReplay,
    ReplayFailureCode,
    ReplayInjectedFailure,
    ReplayVerificationError,
)
from client.spool.session_commit import ValidSessionStager
from client.spool.state_store import SensitiveBlobCodec, StateStore


class StaticKeyProvider:
    def get_key(self) -> bytes:
        return b"r" * 32


def _frame(index: int) -> RawFrame:
    values = np.full((48, 64), index, dtype=np.uint8)
    values.setflags(write=False)
    return RawFrame(
        values=values,
        host_monotonic_ns=1_000_000 + index * 50_000_000,
        host_wall_time_ns=2_000_000 + index * 50_000_000,
        source_index=index,
        device_frame_seq=None,
        device_timestamp_ns=None,
        quality_flags=frozenset(),
    )


@pytest.fixture
def committed_session(tmp_path: Path) -> tuple[Path, StaticKeyProvider]:
    keys = StaticKeyProvider()
    store = StateStore(tmp_path / "state.sqlite3", SensitiveBlobCodec(keys))
    store.put_subject_ref("subject", b"opaque")
    try:
        stager = ValidSessionStager(
            tmp_path / "data",
            session_id="replay-session",
            key_provider=keys,
            store=store,
            subject_uuid="subject",
            consent_id=None,
            versions={"protocol_profile": "observed-compact/1", "quality": "mvp/1"},
            started_at_ns=1_000_000,
        )
        for index in range(102):
            stager.append(_frame(index))
        stager.commit_valid(ended_at_ns=9_000_000_000)
        yield tmp_path / "data", keys
    finally:
        store.close()


def test_verified_replay_steps_ranges_loops_and_exports_no_raw_values(
    committed_session: tuple[Path, StaticKeyProvider],
) -> None:
    root, keys = committed_session
    replay = InternalSessionReplay.open(root, session_id="replay-session", key_provider=keys)

    assert replay.total_frames == 102
    assert replay.seek_source_index(50) == 50
    assert [frame.source_index for frame in replay.frames(start_source_index=50, end_source_index=51, loops=2)] == [50, 51, 50, 51]
    first = next(replay.frames())
    assert replay.relative_time_s(first, speed=2.0) == 0.0
    summary = replay.diagnostic_summary().as_dict()
    assert summary["total_frames"] == 102
    encoded = json.dumps(summary, sort_keys=True)
    assert "raw_count" not in encoded
    assert "values" not in encoded
    assert "protocol" in encoded


@pytest.mark.parametrize(
    "fault",
    [
        ReplayFailureCode.DEVICE_DISCONNECTED,
        ReplayFailureCode.CHECKSUM_ERROR,
        ReplayFailureCode.ALGORITHM_FAILURE,
    ],
)
def test_replay_reproduces_internal_failures_at_deterministic_boundary(
    committed_session: tuple[Path, StaticKeyProvider], fault: ReplayFailureCode
) -> None:
    root, keys = committed_session
    replay = InternalSessionReplay.open(root, session_id="replay-session", key_provider=keys)

    source = replay.frames(inject_failure=fault, fail_after_frames=2)
    assert [next(source).source_index, next(source).source_index] == [0, 1]
    with pytest.raises(ReplayInjectedFailure, match=fault.value) as raised:
        next(source)
    assert raised.value.code is fault


def test_replay_refuses_missing_or_tampered_manifest_segment(
    committed_session: tuple[Path, StaticKeyProvider],
) -> None:
    root, keys = committed_session
    session = root / "sessions" / "replay-session"
    segment = next(session.glob("segment-*.ffps"))
    segment.unlink()

    with pytest.raises(ReplayVerificationError) as raised:
        InternalSessionReplay.open(root, session_id="replay-session", key_provider=keys)
    assert raised.value.code is ReplayFailureCode.MISSING_SEGMENT


def test_replay_refuses_manifest_digest_or_timeline_tampering(
    committed_session: tuple[Path, StaticKeyProvider],
) -> None:
    root, keys = committed_session
    manifest_path = root / "sessions" / "replay-session" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["total_frames"] = 1
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ReplayVerificationError) as raised:
        InternalSessionReplay.open(root, session_id="replay-session", key_provider=keys)
    assert raised.value.code is ReplayFailureCode.MANIFEST_INVALID
