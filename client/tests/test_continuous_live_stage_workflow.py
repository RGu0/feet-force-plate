from __future__ import annotations

from dataclasses import replace
import threading
from types import SimpleNamespace

import numpy as np

from client.app.live_hardware_acquisition import QtLiveHardwareAcquisition
from client.device.protocol import RawFrame
from client.workflow.coordinator import ScreeningCoordinator
from client.workflow.models import (
    PreflightCheck,
    PreflightSummary,
    QualityOutcome,
    QualityResult,
)
from client.workflow.protocol import default_standard_protocol
from client.workflow.state_machine import ScreeningStep


EXPECTED_STAGE_IDS = (
    "BILATERAL_EYES_OPEN",
    "BILATERAL_EYES_CLOSED",
    "SEMI_TANDEM_LEFT_FORWARD",
    "SEMI_TANDEM_RIGHT_FORWARD",
)


class _Preflight:
    def run_preflight(self) -> PreflightSummary:
        return PreflightSummary((PreflightCheck("ready", True),))


class _Sessions:
    def __init__(self) -> None:
        self.finalized: list[str] = []
        self.stages: list[str] = []

    def create_session(self, _context, _protocol) -> str:
        return "physical-session-1"

    def mark_incomplete(self, _session_id: str) -> None:
        raise AssertionError("stage handoff must not mark the session incomplete")

    def mark_stage_complete(self, _session_id: str, stage_id: str) -> None:
        self.stages.append(stage_id)

    def finalize(self, session_id: str) -> None:
        self.finalized.append(session_id)


class _Acquisition:
    continuous_stage_capture = True

    def __init__(self) -> None:
        self.started: list[tuple[str, str]] = []
        self.finished: list[str] = []

    def start_stage(self, session_id, stage) -> None:
        self.started.append((session_id, stage.stage_id))

    def finish(self, session_id: str) -> None:
        self.finished.append(session_id)

    def stop(self, _session_id: str) -> None:
        pass


class _AnalysisAndReports:
    def analyze(self, _session_id: str) -> QualityResult:
        return QualityResult(QualityOutcome.VALID)

    def create_basic_report(self, _session_id: str) -> tuple[str, int]:
        return ("report-1", 1)

    def export_pdf(self, *_args) -> None:
        pass

    def print_report(self, *_args) -> None:
        pass


class _Telemetry:
    def record_error(self, **_event) -> None:
        raise AssertionError("unexpected workflow error")


class _RecordingTelemetry:
    def __init__(self) -> None:
        self.errors: list[dict[str, object]] = []

    def record_error(self, **event) -> None:
        self.errors.append(event)


def _frame_at(seconds: float, source_index: int) -> RawFrame:
    values = np.ones((48, 64), dtype=np.uint8)
    values.setflags(write=False)
    timestamp_ns = round(seconds * 1_000_000_000)
    return RawFrame(
        values=values,
        host_monotonic_ns=timestamp_ns,
        host_wall_time_ns=timestamp_ns,
        source_index=source_index,
        device_frame_seq=None,
        device_timestamp_ns=None,
        quality_flags=frozenset(),
    )


def _ready_live_coordinator() -> tuple[ScreeningCoordinator, _Acquisition]:
    acquisition = _Acquisition()
    coordinator = ScreeningCoordinator(
        preflight=_Preflight(),
        sessions=_Sessions(),
        acquisition=acquisition,
        analysis=_AnalysisAndReports(),
        reports=_AnalysisAndReports(),
        telemetry=_Telemetry(),
    )
    coordinator.bind_participant(
        subject_uuid="subject-1", consent_record_id="consent-1"
    )
    coordinator.start_new_screening()
    coordinator.confirm_subject()
    coordinator.complete_profile()
    coordinator.confirm_consent()
    assert coordinator.run_preflight()
    assert coordinator.enter_position_guidance()
    return coordinator, acquisition


def test_each_live_stage_requires_guidance_and_a_new_operator_start() -> None:
    coordinator, acquisition = _ready_live_coordinator()

    for index, expected_stage in enumerate(EXPECTED_STAGE_IDS):
        assert coordinator.state.step is ScreeningStep.POSITION_GUIDANCE
        assert coordinator.state.stage_index == index + 1
        assert coordinator.start_acquisition()
        assert acquisition.started[-1] == ("physical-session-1", expected_stage)
        coordinator.observe_acquisition_elapsed(elapsed_seconds=20)

    assert coordinator.state.step is ScreeningStep.FINALIZING
    assert len(acquisition.started) == 4
    assert acquisition.finished == ["physical-session-1"]


def test_durable_nonfinal_completion_is_reconciled_before_worker_failure(qtbot) -> None:
    first_worker_exited = threading.Event()
    capture_calls = 0

    def capture(_session_id: str, gate):
        nonlocal capture_calls
        capture_calls += 1
        if capture_calls == 1:
            gate.observe(_frame_at(10, 0))
            decision = gate.observe(_frame_at(30, 1))
            assert gate.begin_stage_commit(decision.window)
            gate.complete_stage_commit(decision.window)
            first_worker_exited.set()
            raise RuntimeError("serial disconnected after durable stage commit")
        gate.observe(_frame_at(40, 2))
        decision = gate.observe(_frame_at(60, 3))
        assert gate.begin_stage_commit(decision.window)
        gate.complete_stage_commit(decision.window)
        return SimpleNamespace(
            committed=True,
            stage_windows=gate.snapshot().completed_windows,
        )

    protocol = replace(
        default_standard_protocol(),
        acquisition_duration_seconds=40,
        stages=default_standard_protocol().stages[:2],
    )
    acquisition = QtLiveHardwareAcquisition(
        capture,
        expected_stage_ids=tuple(stage.stage_id for stage in protocol.stages),
    )
    sessions = _Sessions()
    telemetry = _RecordingTelemetry()
    coordinator = ScreeningCoordinator(
        preflight=_Preflight(), sessions=sessions, acquisition=acquisition,
        analysis=_AnalysisAndReports(), reports=_AnalysisAndReports(),
        telemetry=telemetry, protocol=protocol,
    )
    coordinator.bind_participant(
        subject_uuid="subject-1", consent_record_id="consent-1"
    )
    coordinator.start_new_screening()
    coordinator.confirm_subject()
    coordinator.complete_profile()
    coordinator.confirm_consent()
    assert coordinator.run_preflight()
    assert coordinator.enter_position_guidance()
    failures: list[str] = []
    completed: list[object] = []
    progress: list[int] = []

    def observe_progress(elapsed: int) -> None:
        progress.append(elapsed)
        coordinator.observe_acquisition_elapsed(elapsed_seconds=elapsed)

    acquisition.set_callbacks(
        on_progress=observe_progress,
        on_complete=completed.append,
        on_failure=lambda detail: (
            failures.append(detail),
            coordinator.handle_stage_capture_failure(technical_detail=detail),
        ),
    )

    assert coordinator.start_acquisition()
    session_id = coordinator.state.session_id
    assert first_worker_exited.wait(timeout=2)
    qtbot.waitUntil(
        lambda: coordinator.state.step is ScreeningStep.POSITION_GUIDANCE
        and coordinator.state.stage_index == 2
    )

    assert coordinator.state.session_id == session_id
    assert sessions.stages == ["BILATERAL_EYES_OPEN"]
    qtbot.wait(150)
    assert progress.count(20) == 1
    assert failures == []
    assert telemetry.errors == []
    assert coordinator.start_acquisition()
    qtbot.waitUntil(lambda: bool(completed))
    assert capture_calls == 2
    assert [window.stage_id for window in completed[0].stage_windows] == [
        "BILATERAL_EYES_OPEN",
        "BILATERAL_EYES_CLOSED",
    ]
