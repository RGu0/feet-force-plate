from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from queue import Queue
import threading
import time
from types import SimpleNamespace

import numpy as np

from client.app.live_physical_workflow import (
    LivePhysicalCapture,
    LiveSessionMetadata,
    RetryableStageCaptureError,
)
from client.device.acquisition import LatestFrameMailbox
from client.device.protocol import ProtocolIntegrityEvent, RawFrame
from client.device.stage_windows import CapturedStageWindow, StageRecordingGate
from client.device.transport import TransportDisconnected
from client.hardware_standardization.do_p4864 import DoP4864StandardizationAdapter
from client.hardware_standardization.models import BaselineReference
from client.spool.derived_artifact import read_derived_observation
from client.spool.segments import read_segment
from client.spool.state_store import SensitiveBlobCodec, StateStore


class _KeyProvider:
    def get_key(self) -> bytes:
        return b"g" * 32


@dataclass(frozen=True)
class _Packet:
    frames: tuple[RawFrame, ...]
    events: tuple[ProtocolIntegrityEvent, ...] = ()


class _Disconnect:
    pass


class _ControlledTransport:
    def __init__(self) -> None:
        self._packets: Queue[object] = Queue()
        self.closed = False

    def push(
        self,
        frame: RawFrame,
        *,
        events: tuple[ProtocolIntegrityEvent, ...] = (),
    ) -> None:
        self._packets.put(_Packet((frame,), events))

    def disconnect(self) -> None:
        self._packets.put(_Disconnect())

    def read(self, _max_bytes: int) -> object:
        packet = self._packets.get(timeout=2)
        if isinstance(packet, _Disconnect):
            raise TransportDisconnected("controlled disconnect")
        return packet

    def close(self) -> None:
        self.closed = True


class _ControlledParser:
    profile = SimpleNamespace(version="controlled-stage-stream/1")

    def __init__(self) -> None:
        self._events: tuple[ProtocolIntegrityEvent, ...] = ()

    def feed(self, packet: _Packet) -> tuple[RawFrame, ...]:
        self._events = packet.events
        return packet.frames

    def take_integrity_events(self) -> tuple[ProtocolIntegrityEvent, ...]:
        events, self._events = self._events, ()
        return events


class _ControlledHardware:
    def __init__(self) -> None:
        self.connections: list[_ControlledTransport] = []

    def connect_startup(self):
        transport = _ControlledTransport()
        self.connections.append(transport)
        return SimpleNamespace(transport=transport, parser=_ControlledParser())


class _Sessions:
    def metadata(self, session_id: str) -> LiveSessionMetadata:
        return LiveSessionMetadata(
            subject_uuid=f"subject-{session_id}",
            consent_record_id=f"consent-{session_id}",
            captured_at=datetime.now(UTC),
        )


class _Baseline:
    def __init__(self) -> None:
        adapter = DoP4864StandardizationAdapter.observed_compact_8bit()
        self.reference = BaselineReference(
            schema_version="baseline-reference/1",
            baseline_window_id="baseline-1",
            layout_digest=adapter.layout.digest,
            zero_offset_count=(0.0,) * (48 * 64),
            noise_mad_count=(0.0,) * (48 * 64),
            rules_version="baseline-rules/1",
            threshold_version="baseline-threshold/1",
            source_digest="0" * 64,
        )


def _frame_at(seconds: float, value: int, source_index: int) -> RawFrame:
    values = np.full((48, 64), value, dtype=np.uint8)
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


def _capture_fixture(tmp_path):
    hardware = _ControlledHardware()
    key_provider = _KeyProvider()
    physical_store = StateStore(
        tmp_path / "physical.sqlite3", SensitiveBlobCodec(key_provider)
    )
    mailbox = LatestFrameMailbox()
    capture = LivePhysicalCapture(
        hardware=hardware,
        sessions=_Sessions(),
        baseline=_Baseline(),
        physical_store=physical_store,
        key_provider=key_provider,
        spool_root=tmp_path / "spool",
        latest_frames=mailbox,
    )
    return capture, hardware, key_provider, mailbox


def _start_capture(capture: LivePhysicalCapture, gate: StageRecordingGate):
    results: Queue[object] = Queue()

    def _run() -> None:
        try:
            results.put(capture.capture("session-1", gate))
        except BaseException as exc:  # propagate the exact worker outcome to the test
            results.put(exc)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return thread, results


def _wait_until(predicate, *, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError("condition was not reached before timeout")
        time.sleep(0.005)


def _push_stage(
    transport: _ControlledTransport,
    *,
    start_s: int,
    first_value: int,
    first_source_index: int,
    integrity_event_offset: int | None = None,
) -> None:
    for offset, seconds_offset in enumerate((0, 3, 6, 9, 12, 15, 18, 20)):
        seconds = start_s + seconds_offset
        source_index = first_source_index + offset
        events = (
            (
                ProtocolIntegrityEvent(
                    8, source_index, "FUNCTION", 1, 3079
                ),
            )
            if offset == integrity_event_offset
            else ()
        )
        transport.push(
            _frame_at(seconds, first_value + offset, source_index), events=events
        )


def _read_committed_raw_values(tmp_path, key_provider: _KeyProvider) -> list[int]:
    frames = []
    for path in sorted(
        (tmp_path / "spool" / "sessions" / "session-1").glob("segment-*.ffps")
    ):
        frames.extend(read_segment(path, key_provider).frames)
    return [int(frame.values[0, 0]) for frame in frames]


def test_capture_keeps_one_connection_and_never_stages_preparation_frames(tmp_path) -> None:
    capture, hardware, key_provider, mailbox = _capture_fixture(tmp_path)
    gate = StageRecordingGate(expected_stage_ids=("one", "two"))
    thread, results = _start_capture(capture, gate)
    _wait_until(lambda: len(hardware.connections) == 1)
    transport = hardware.connections[0]

    transport.push(_frame_at(1, 1, 0))
    _wait_until(lambda: mailbox.publish_count == 1)
    gate.open_stage("one", duration_seconds=20)
    _push_stage(
        transport, start_s=10, first_value=10, first_source_index=1
    )
    _wait_until(lambda: gate.snapshot().stage_complete)

    transport.push(
        _frame_at(35, 250, 9),
        events=(ProtocolIntegrityEvent(7, 9, "TAIL", 1, 3079),),
    )
    _wait_until(lambda: mailbox.publish_count == 10)
    gate.open_stage("two", duration_seconds=20)
    _push_stage(
        transport,
        start_s=60,
        first_value=20,
        first_source_index=10,
        integrity_event_offset=1,
    )

    result = results.get(timeout=3)
    thread.join(timeout=1)
    assert not isinstance(result, BaseException)
    assert result.committed
    assert result.stage_windows == (
        CapturedStageWindow("one", 0.0, 20.0, 8),
        CapturedStageWindow("two", 50.0, 70.0, 8),
    )
    assert [event.event_index for event in result.acquisition.integrity_events] == [8]
    assert len(result.acquisition.reconstructed_frames) == 1
    assert _read_committed_raw_values(tmp_path, key_provider) == [
        10, 11, 12, 13, 14, 15, 16, 17, 20, 21, 22, 23, 24, 25, 26, 27
    ]
    assert 250 not in _read_committed_raw_values(tmp_path, key_provider)
    assert len(hardware.connections) == 1
    assert transport.closed

    derived_path = next(
        (tmp_path / "spool" / "sessions" / "session-1").glob("derived-*.ffpd")
    )
    derived = read_derived_observation(derived_path, key_provider=key_provider)
    assert derived["hardware_processing"]["stage_windows"] == [
        {"stage_id": "one", "start_s": 0.0, "end_s": 20.0, "frame_count": 8},
        {"stage_id": "two", "start_s": 50.0, "end_s": 70.0, "frame_count": 8},
    ]
    assert [
        event["event_index"]
        for event in derived["hardware_processing"]["communication_integrity"]["events"]
    ] == [8]


def test_cancel_before_first_stage_frame_stops_worker_and_allows_retry(tmp_path) -> None:
    capture, hardware, _key_provider, _mailbox = _capture_fixture(tmp_path)
    gate = StageRecordingGate(expected_stage_ids=("one",))
    thread, results = _start_capture(capture, gate)
    _wait_until(lambda: len(hardware.connections) == 1)
    transport = hardware.connections[0]

    gate.open_stage("one", duration_seconds=20)
    gate.cancel_current_stage()
    transport.push(_frame_at(1, 1, 0))

    outcome = results.get(timeout=3)
    thread.join(timeout=1)
    assert isinstance(outcome, RetryableStageCaptureError)
    assert transport.closed
    gate.open_stage("one", duration_seconds=20)


def test_retry_discards_only_failed_stage_and_reuses_completed_stage(tmp_path) -> None:
    capture, hardware, key_provider, _mailbox = _capture_fixture(tmp_path)
    gate = StageRecordingGate(expected_stage_ids=("one", "two"))
    first_thread, first_results = _start_capture(capture, gate)
    _wait_until(lambda: len(hardware.connections) == 1)
    first_transport = hardware.connections[0]

    gate.open_stage("one", duration_seconds=20)
    _push_stage(
        first_transport, start_s=10, first_value=10, first_source_index=0
    )
    _wait_until(lambda: gate.snapshot().stage_complete)
    gate.open_stage("two", duration_seconds=20)
    first_transport.push(_frame_at(60, 99, 8))
    first_transport.disconnect()

    first_outcome = first_results.get(timeout=3)
    first_thread.join(timeout=1)
    assert isinstance(first_outcome, RetryableStageCaptureError)
    assert gate.snapshot().cancelled
    assert first_transport.closed

    gate.open_stage("two", duration_seconds=20)
    second_thread, second_results = _start_capture(capture, gate)
    _wait_until(lambda: len(hardware.connections) == 2)
    second_transport = hardware.connections[1]
    _push_stage(
        second_transport, start_s=70, first_value=20, first_source_index=0
    )

    result = second_results.get(timeout=3)
    second_thread.join(timeout=1)
    assert not isinstance(result, BaseException)
    assert result.committed
    assert result.stage_windows == (
        CapturedStageWindow("one", 0.0, 20.0, 8),
        CapturedStageWindow("two", 60.0, 80.0, 8),
    )
    assert _read_committed_raw_values(tmp_path, key_provider) == [
        10, 11, 12, 13, 14, 15, 16, 17, 20, 21, 22, 23, 24, 25, 26, 27
    ]
    assert 99 not in _read_committed_raw_values(tmp_path, key_provider)
    assert len(hardware.connections) == 2
    assert second_transport.closed
