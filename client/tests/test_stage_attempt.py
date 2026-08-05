from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from client.device.protocol import RawFrame
from client.device.stage_windows import CapturedStageWindow
from client.hardware_standardization.models import (
    CellStatus,
    FrameQuality,
    MeasurementProfile,
    MeasurementUncertainty,
    PhysicalArrayCell,
    PhysicalArrayFrame,
    PhysicalArraySession,
)
from client.spool.derived_artifact import read_derived_observation
from client.spool.segments import read_segment
from client.spool import session_commit
from client.spool.session_commit import FinalSessionStorageError, ValidSessionStager
from client.spool.stage_attempt import SealedStageAttempt, StageAttemptSpool
from client.spool.state_store import SensitiveBlobCodec, StateStore


class _KeyProvider:
    def get_key(self) -> bytes:
        return b"a" * 32


def _frame(index: int, *, seconds: float | None = None) -> RawFrame:
    values = np.full((48, 64), index, dtype=np.uint8)
    values.setflags(write=False)
    monotonic_ns = (
        index * 50_000_000
        if seconds is None
        else round(seconds * 1_000_000_000)
    )
    return RawFrame(
        values=values,
        host_monotonic_ns=monotonic_ns,
        host_wall_time_ns=1_000_000_000 + monotonic_ns,
        source_index=index,
        device_frame_seq=None,
        device_timestamp_ns=None,
        quality_flags=frozenset(),
    )


def _window(
    stage_id: str,
    start_s: float,
    end_s: float,
    *,
    frame_count: int = 1,
) -> CapturedStageWindow:
    return CapturedStageWindow(stage_id, start_s, end_s, frame_count)


def _attempt(
    tmp_path, stage_id: str, *, session_id: str = "session-1"
) -> StageAttemptSpool:
    return StageAttemptSpool(
        tmp_path,
        session_id=session_id,
        stage_id=stage_id,
        key_provider=_KeyProvider(),
        versions={"protocol": "test/1"},
    )


def _valid_session_stager(tmp_path) -> ValidSessionStager:
    keys = _KeyProvider()
    store = StateStore(tmp_path / "state.sqlite3", SensitiveBlobCodec(keys))
    store.put_subject_ref("subject-1", b"opaque")
    return ValidSessionStager(
        tmp_path / "data",
        session_id="session-1",
        key_provider=keys,
        store=store,
        subject_uuid="subject-1",
        consent_id=None,
        versions={"protocol": "test/1"},
        started_at_ns=1,
        expected_stage_ids=("stage-1", "stage-2", "stage-3", "stage-4"),
    )


def _physical_session() -> PhysicalArraySession:
    return PhysicalArraySession(
        schema_version="estimated-force-session/1.0",
        session_id="session-1",
        coordinate_frame="BOARD_TOP_LEFT_X_RIGHT_Y_DOWN",
        coordinate_unit="mm",
        raw_value_unit="count",
        relative_value_unit="relative_count",
        force_unit="N",
        measurement_profile=MeasurementProfile(
            profile_version="test/1",
            geometry_validation="TEST",
            baseline_validation="TEST",
            force_validation="MVP_SCREENING_ESTIMATED_TEST",
            timing_validation="TEST",
            active_area_validation="UNAVAILABLE",
            uncertainty_profile_version="test/1",
        ),
        uncertainty=MeasurementUncertainty("test/1", None, None, None, None, "TEST"),
        cells=(PhysicalArrayCell("cell-1", 0, 0.0, 0.0, None, CellStatus.ACTIVE),),
        frames=(
            PhysicalArrayFrame(
                timestamp_s=0.0,
                raw_count=(1,),
                zero_corrected_count=(1.0,),
                relative_load_count=(1.0,),
                quality=FrameQuality.VALID,
                quality_flags=frozenset(),
                estimated_force_n=(1.0,),
            ),
        ),
        adapter_version="test/1",
        geometry_version="test/1",
        source_schema_version="test/1",
    )


def test_failed_stage_attempt_is_deleted_without_touching_previous_stage(tmp_path):
    first = _attempt(tmp_path, "stage-1")
    first.append(_frame(0))
    assert len(first.seal().frames) == 1
    second = _attempt(tmp_path, "stage-2")
    second.append(_frame(1))
    second.discard(reason="operator retry")
    assert not second.staging_directory.exists()
    assert first.staging_directory.exists()


def test_stage_attempt_seals_verified_encrypted_frames_in_a_unique_directory(tmp_path):
    first = _attempt(tmp_path, "stage-1")
    second = _attempt(tmp_path, "stage-1")
    first.append(_frame(0))

    sealed = first.seal()

    assert first.staging_directory != second.staging_directory
    assert first.staging_directory.parent.name == "stage-1"
    assert [frame.source_index for frame in sealed.frames] == [0]
    assert len(tuple(first.staging_directory.rglob("*.ffps"))) == 1


def test_final_stager_merges_four_sealed_attempts_in_stage_order(tmp_path):
    stager = _valid_session_stager(tmp_path)
    windows = tuple(
        _window(f"stage-{index + 1}", index * 20, (index + 1) * 20)
        for index in range(4)
    )

    for index, window in enumerate(windows):
        attempt = _attempt(tmp_path, window.stage_id)
        attempt.append(_frame(index))
        stager.append_verified_stage(attempt.seal(), window)

    assert stager.stage_windows == windows
    assert [frame.source_index for frame in stager.staged_frames()] == [0, 1, 2, 3]


def test_verified_stage_merge_rolls_back_a_segment_written_before_failure(
    tmp_path, monkeypatch
):
    stager = _valid_session_stager(tmp_path)
    first = _attempt(tmp_path, "stage-1")
    first.append(_frame(0, seconds=0))
    stager.append_verified_stage(
        first.seal(), _window("stage-1", 0, 20)
    )
    assert [frame.source_index for frame in stager.staged_frames()] == [0]

    failed = _attempt(tmp_path, "stage-2")
    failed.append(_frame(1, seconds=30))
    failed.append(_frame(2, seconds=36))
    original_close = stager._writer.close

    def _write_then_fail():
        original_close()
        raise OSError("injected failure after encrypted segment write")

    monkeypatch.setattr(stager._writer, "close", _write_then_fail)

    with pytest.raises(OSError, match="injected failure"):
        stager.append_verified_stage(
            failed.seal(),
            _window("stage-2", 30, 50, frame_count=2),
        )

    monkeypatch.setattr(stager._writer, "close", original_close)
    assert stager.stage_windows == (_window("stage-1", 0, 20),)
    assert [frame.source_index for frame in stager.staged_frames()] == [0]
    assert len(tuple(stager.staging_directory.glob("segment-*.ffps"))) == 1

    retry = _attempt(tmp_path, "stage-2")
    retry.append(_frame(1, seconds=40))
    retry.append(_frame(2, seconds=46))
    stager.append_verified_stage(
        retry.seal(),
        _window("stage-2", 40, 60, frame_count=2),
    )

    assert [frame.source_index for frame in stager.staged_frames()] == [0, 1, 2]
    assert [window.stage_id for window in stager.stage_windows] == [
        "stage-1",
        "stage-2",
    ]


@pytest.mark.parametrize("cleanup_failure", ("unlink", "rmtree", "fsync"))
def test_failed_rollback_cleanup_poisoned_stager_rejects_append_and_commit(
    tmp_path, monkeypatch, cleanup_failure: str
) -> None:
    stager = _valid_session_stager(tmp_path)
    first = _attempt(tmp_path, "stage-1")
    first.append(_frame(0, seconds=0))
    stager.append_verified_stage(first.seal(), _window("stage-1", 0, 20))
    existing_paths = frozenset(stager.staging_directory.iterdir())

    failed = _attempt(tmp_path, "stage-2")
    failed.append(_frame(1, seconds=30))
    failed.append(_frame(2, seconds=36))
    sealed_failed = failed.seal()
    original_close = stager._writer.close

    def _write_then_fail():
        original_close()
        if cleanup_failure == "rmtree":
            (stager.staging_directory / "rollback-new-directory").mkdir()
        raise OSError("controlled final-writer failure")

    monkeypatch.setattr(stager._writer, "close", _write_then_fail)
    if cleanup_failure == "unlink":
        original_unlink = Path.unlink

        def _fail_new_segment_unlink(path, *args, **kwargs):
            if path.parent == stager.staging_directory and path not in existing_paths:
                raise OSError("controlled unlink failure")
            return original_unlink(path, *args, **kwargs)

        monkeypatch.setattr(Path, "unlink", _fail_new_segment_unlink)
    elif cleanup_failure == "rmtree":
        original_rmtree = session_commit.shutil.rmtree

        def _fail_new_directory_rmtree(path, *args, **kwargs):
            if Path(path).name == "rollback-new-directory":
                raise OSError("controlled rmtree failure")
            return original_rmtree(path, *args, **kwargs)

        monkeypatch.setattr(
            session_commit.shutil, "rmtree", _fail_new_directory_rmtree
        )
    else:
        monkeypatch.setattr(
            session_commit,
            "_fsync_directory",
            lambda _path: (_ for _ in ()).throw(OSError("controlled fsync failure")),
        )

    with pytest.raises(FinalSessionStorageError):
        stager.append_verified_stage(
            sealed_failed,
            _window("stage-2", 30, 50, frame_count=2),
        )

    with pytest.raises(FinalSessionStorageError, match="poisoned"):
        stager.append(_frame(3, seconds=60))
    with pytest.raises(FinalSessionStorageError, match="poisoned"):
        stager.commit_valid(ended_at_ns=100)


def test_final_stager_rejects_duplicate_stage_and_retains_immutable_windows(tmp_path):
    stager = _valid_session_stager(tmp_path)
    first = _window("stage-1", 0, 20)
    first_attempt = _attempt(tmp_path, "stage-1")
    first_attempt.append(_frame(0))
    stager.append_verified_stage(first_attempt.seal(), first)

    duplicate = _attempt(tmp_path, "stage-1")
    duplicate.append(_frame(1))
    with pytest.raises(ValueError, match="duplicate stage"):
        stager.append_verified_stage(duplicate.seal(), _window("stage-1", 20, 40))

    assert stager.stage_windows == (first,)


def test_derived_observation_includes_stage_windows_and_frozen_policy_version(tmp_path):
    stager = _valid_session_stager(tmp_path)
    window = _window("stage-1", 0, 20)
    attempt = _attempt(tmp_path, "stage-1")
    attempt.append(_frame(0))
    stager.append_verified_stage(attempt.seal(), window)

    artifact = stager.stage_derived_observation(_physical_session())
    derived = read_derived_observation(artifact.path, key_provider=_KeyProvider())
    assert [frame.source_index for frame in stager.staged_frames()] == [0]
    segment = read_segment(
        next((tmp_path / "data" / ".staging" / "session-1").glob("*.ffps")),
        _KeyProvider(),
    )

    assert derived["hardware_processing"]["stage_windows"] == [
        {"stage_id": "stage-1", "start_s": 0, "end_s": 20, "frame_count": 1}
    ]
    assert "subject-1" not in str(derived["hardware_processing"])
    assert segment.versions["stage_window_policy"] == "operator-started-stage-window/1"


def test_final_stager_rejects_unsealed_tuples_and_mismatched_attempt_identity(tmp_path):
    stager = _valid_session_stager(tmp_path)

    with pytest.raises(TypeError, match="sealed stage attempt"):
        stager.append_verified_stage((_frame(0),), _window("stage-1", 0, 20))

    wrong_session = _attempt(tmp_path, "stage-1", session_id="session-2")
    wrong_session.append(_frame(0))
    with pytest.raises(ValueError, match="session identity"):
        stager.append_verified_stage(wrong_session.seal(), _window("stage-1", 0, 20))

    wrong_stage = _attempt(tmp_path, "stage-1")
    wrong_stage.append(_frame(0))
    with pytest.raises(ValueError, match="stage identity"):
        stager.append_verified_stage(wrong_stage.seal(), _window("stage-2", 20, 40))


def test_sealed_stage_attempt_cannot_be_constructed_without_verified_provenance():
    with pytest.raises(TypeError, match="only StageAttemptSpool.seal"):
        SealedStageAttempt(
            session_id="session-1",
            stage_id="stage-1",
            attempt_id="not-a-real-attempt",
            frames=(_frame(0),),
        )
