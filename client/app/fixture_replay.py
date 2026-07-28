"""Verified four-stage fixture source for the local V1 replay runtime."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from dataclasses import replace

import numpy as np
from PySide6.QtCore import QObject, QTimer

from client.device.protocol import RawFrame
from client.hardware_standardization.live_processing import FrameStandardizer
from client.workflow.models import PreflightCheck, PreflightSummary


_POSES = (
    ("BILATERAL_EYES_OPEN", "open_eyes_bilateral"),
    ("BILATERAL_EYES_CLOSED", "closed_eyes_bilateral"),
    ("SEMI_TANDEM_LEFT_FORWARD", "tandem_left_front"),
    ("SEMI_TANDEM_RIGHT_FORWARD", "tandem_right_front"),
)


class FixtureReplayBootstrap:
    """Validate the fixed fixture before the workflow exposes its workbench."""

    def __init__(self, source_factory) -> None:
        try:
            self.source = source_factory()
            self._error: str | None = None
        except ValueError as exc:
            self.source = None
            self._error = str(exc)

    def preflight_summary(self) -> PreflightSummary:
        device = (
            PreflightCheck(
                "device_connected",
                True,
                operator_message="回放数据源已就绪",
            )
            if self._error is None
            else
                PreflightCheck(
                    "device_connected",
                    False,
                    error_code="E-FIX-001",
                    operator_message="回放调试数据不可用，请联系技术支持",
                )
        )
        free_bytes = shutil.disk_usage(Path.home()).free
        storage_ready = free_bytes >= 512 * 1024 * 1024
        return PreflightSummary(
            (
                device,
                PreflightCheck(
                    "storage_space",
                    storage_ready,
                    error_code=None if storage_ready else "E-DAT-002",
                    operator_message=(
                        "空间充足"
                        if storage_ready
                        else "本机存储空间不足，请清理后重新检查"
                    ),
                ),
                PreflightCheck(
                    "calibration_status",
                    self._error is None,
                    error_code=None if self._error is None else "E-CAL-001",
                    operator_message=(
                        "回放模式，不适用"
                        if self._error is None
                        else "标准化配置不可用"
                    ),
                ),
                PreflightCheck(
                    "data_sync",
                    True,
                    operator_message="本地调试，无需云端同步",
                ),
            )
        )

    def run_preflight(self) -> PreflightSummary:
        return self.preflight_summary()


class UnavailableFixtureReplaySource:
    """Composition placeholder; preflight prevents it from ever acquiring data."""

    fixture_sha256 = "unavailable"
    stage_ids: tuple[str, ...] = ()

    def frames_for(self, stage_id: str):
        raise RuntimeError(f"fixture replay unavailable: {stage_id}")


class FixtureReplaySource:
    def __init__(self, fixture: Path, metadata: Path) -> None:
        details = json.loads(metadata.read_text(encoding="utf-8"))
        observed = hashlib.sha256(fixture.read_bytes()).hexdigest()
        if observed != details["fixture_sha256"]:
            raise ValueError("回放数据完整性校验失败")
        if details.get("nominal_frame_interval_ms") != 50:
            raise ValueError("回放数据采样间隔不受支持")
        self.fixture_sha256 = observed
        self._frames: dict[str, np.ndarray] = {}
        with np.load(fixture, allow_pickle=False) as source:
            for stage_id, pose in _POSES:
                values = np.asarray(source[pose])
                if values.ndim != 3 or values.shape[1:] != (48, 64) or len(values) < 400:
                    raise ValueError(f"回放阶段数据不完整：{stage_id}")
                if values.dtype != np.uint8:
                    raise ValueError(f"回放阶段数据类型不受支持：{stage_id}")
                self._frames[stage_id] = values.copy()

    @classmethod
    def from_repository(cls, anchor: Path | None = None) -> "FixtureReplaySource":
        root = Path(__file__).resolve().parents[2] if anchor is None else anchor.resolve().parents[2]
        directory = root / "tests" / "fixtures" / "device" / "dop4864_reference_protocol_v1"
        return cls(directory / "reference-poses.npz", directory / "metadata.json")

    @property
    def stage_ids(self) -> tuple[str, ...]:
        return tuple(stage_id for stage_id, _ in _POSES)

    def frames_for(self, stage_id: str):
        try:
            values = self._frames[stage_id]
        except KeyError as exc:
            raise KeyError(f"未知回放阶段：{stage_id}") from exc
        for index, matrix in enumerate(values):
            copied = matrix.copy()
            copied.setflags(write=False)
            yield RawFrame(
                values=copied,
                host_monotonic_ns=index * 50_000_000,
                host_wall_time_ns=index * 50_000_000,
                source_index=index,
                device_frame_seq=None,
                device_timestamp_ns=None,
                quality_flags=frozenset({"FIXTURE_REPLAY", "UNSCALED_RELATIVE_COUNTS"}),
            )


class StandardizedReplaySource:
    """Apply the same declared hardware path to replay analysis input.

    The fixture remains immutable; callers receive a new standardized raw-frame
    derivative for every stage.  Live display applies the same standardizer to
    its mailbox input, so neither UI nor local analysis can bypass it.
    """

    def __init__(self, source: FixtureReplaySource, standardizer: FrameStandardizer) -> None:
        self._source = source
        self._standardizer = standardizer
        self.fixture_sha256 = source.fixture_sha256

    @property
    def processing_profile_version(self) -> str | None:
        return getattr(self._standardizer, "profile_version", None)

    @property
    def stage_ids(self) -> tuple[str, ...]:
        return self._source.stage_ids

    def frames_for(self, stage_id: str):
        for frame in self._source.frames_for(stage_id):
            yield self._standardizer.standardize(frame)


class FixtureReplayAcquisition(QObject):
    """Qt-thread replay adapter; it emits the same latest-frame contract as hardware."""

    def __init__(self, source: FixtureReplaySource, mailbox, *, speed: float = 1.0) -> None:
        super().__init__()
        if speed <= 0:
            raise ValueError("replay speed must be positive")
        self._source, self._mailbox = source, mailbox
        self._timer = QTimer(self)
        self._timer.setInterval(max(1, round(50 / speed)))
        self._frames_per_tick = max(1, round(speed / 50))
        self._progress_interval_frames = (
            20 if speed <= 1 else max(20, round(20 * speed))
        )
        self._timer.timeout.connect(self._tick)
        self._frames = iter(())
        self._elapsed = 0
        self._source_index = 0
        self._on_progress = lambda seconds: None
        self._on_complete = lambda: None

    def set_callbacks(self, *, on_progress, on_complete) -> None:
        self._on_progress, self._on_complete = on_progress, on_complete

    def start_stage(self, session_id: str, stage) -> None:
        _ = session_id
        self._frames = iter(self._source.frames_for(stage.stage_id))
        self._elapsed = 0
        self._timer.start()

    def stop(self, session_id: str) -> None:
        _ = session_id
        self._timer.stop()

    def start(self, session_id: str) -> None:
        raise RuntimeError("fixture replay requires a V1 stage")

    def _tick(self) -> None:
        for _ in range(self._frames_per_tick):
            try:
                frame = next(self._frames)
            except StopIteration:
                self._timer.stop()
                self._on_complete()
                return
            frame = replace(frame, source_index=self._source_index)
            self._source_index += 1
            self._mailbox.publish(frame)
            self._elapsed += 1
            if self._elapsed % self._progress_interval_frames == 0:
                self._on_progress(min(20, self._elapsed // 20))
