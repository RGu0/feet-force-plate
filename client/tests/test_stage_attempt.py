from __future__ import annotations

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
from client.spool.session_commit import ValidSessionStager
from client.spool.stage_attempt import StageAttemptSpool
from client.spool.state_store import SensitiveBlobCodec, StateStore


class _KeyProvider:
    def get_key(self) -> bytes:
        return b"a" * 32


def _frame(index: int) -> RawFrame:
    values = np.full((48, 64), index, dtype=np.uint8)
    values.setflags(write=False)
    return RawFrame(
        values=values,
        host_monotonic_ns=index * 50_000_000,
        host_wall_time_ns=1_000_000_000 + index * 50_000_000,
        source_index=index,
        device_frame_seq=None,
        device_timestamp_ns=None,
        quality_flags=frozenset(),
    )


def _window(stage_id: str, start_s: float, end_s: float) -> CapturedStageWindow:
    return CapturedStageWindow(stage_id, start_s, end_s, 1)


def _attempt(tmp_path, stage_id: str) -> StageAttemptSpool:
    return StageAttemptSpool(
        tmp_path,
        session_id="session-1",
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
        expected_stage_ids=("stage-1", "stage-2", "stage-3"),
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
    assert len(first.seal()) == 1
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
    assert [frame.source_index for frame in sealed] == [0]
    assert len(tuple(first.staging_directory.rglob("*.ffps"))) == 1


def test_final_stager_accepts_only_sealed_stage_frames_in_order(tmp_path):
    stager = _valid_session_stager(tmp_path)
    stager.append_verified_stage("stage-1", (_frame(0),), _window("stage-1", 0, 20))
    with pytest.raises(ValueError, match="stage order"):
        stager.append_verified_stage("stage-3", (_frame(2),), _window("stage-3", 40, 60))


def test_final_stager_rejects_duplicate_stage_and_retains_immutable_windows(tmp_path):
    stager = _valid_session_stager(tmp_path)
    first = _window("stage-1", 0, 20)
    stager.append_verified_stage("stage-1", (_frame(0),), first)

    with pytest.raises(ValueError, match="duplicate stage"):
        stager.append_verified_stage("stage-1", (_frame(1),), _window("stage-1", 20, 40))

    assert stager.stage_windows == (first,)


def test_derived_observation_includes_stage_windows_and_frozen_policy_version(tmp_path):
    stager = _valid_session_stager(tmp_path)
    window = _window("stage-1", 0, 20)
    stager.append_verified_stage("stage-1", (_frame(0),), window)

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
