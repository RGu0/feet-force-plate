import threading
import unittest

import numpy as np

from client.device.acquisition import (
    AcquisitionOutcome,
    AcquisitionRunner,
    AcquisitionWorker,
    ConnectionState,
    ConnectionStateMachine,
    DurableFrameQueue,
    IllegalConnectionTransition,
    LatestFrameMailbox,
)
from client.device.protocol import DaoOneP4864Parser, ProtocolProfile
from client.device.simulator import FaultKind, FaultPlan, SyntheticP4864Transport


def _profile() -> ProtocolProfile:
    return ProtocolProfile.synthetic(
        version="do-p4864/synthetic-acquisition-test-1",
        length_byte_order="little",
        checksum_start=0,
        checksum_end=3077,
    )


def _parser() -> DaoOneP4864Parser:
    ticks = iter(range(1_000, 100_000))
    return DaoOneP4864Parser(
        _profile(),
        allow_unverified=True,
        monotonic_ns=lambda: next(ticks),
        wall_time_ns=lambda: 2_000,
    )


class ConnectionStateTests(unittest.TestCase):
    def test_state_machine_allows_only_explicit_connection_transitions(self) -> None:
        machine = ConnectionStateMachine()

        machine.start_connecting()
        machine.mark_ready()
        machine.start_acquiring()
        machine.finish_acquiring()

        self.assertEqual(machine.state, ConnectionState.READY)
        with self.assertRaises(IllegalConnectionTransition):
            machine.mark_ready()

    def test_reconnect_after_error_stops_at_ready(self) -> None:
        machine = ConnectionStateMachine()
        machine.start_connecting()
        machine.mark_ready()
        machine.start_acquiring()
        machine.mark_error("cable removed")

        machine.start_connecting()
        machine.mark_ready()

        self.assertEqual(machine.state, ConnectionState.READY)
        self.assertIsNone(machine.last_error)


class AcquisitionRunnerTests(unittest.TestCase):
    def _ready_machine(self) -> ConnectionStateMachine:
        machine = ConnectionStateMachine()
        machine.start_connecting()
        machine.mark_ready()
        return machine

    def test_storage_queue_precedes_latest_mailbox_and_preserves_audit_fields(self) -> None:
        events: list[tuple[str, int]] = []

        class RecordingQueue(DurableFrameQueue):
            def append(self, session_id, frame, *, timeout=None):
                events.append(("durable", frame.source_index))
                super().append(session_id, frame, timeout=timeout)

        class RecordingMailbox(LatestFrameMailbox):
            def publish(self, frame):
                events.append(("latest", frame.source_index))
                super().publish(frame)

        transport = SyntheticP4864Transport(
            _profile(),
            realtime=False,
            max_frames=3,
            frame_source=lambda index: np.full((48, 64), index + 1, dtype=np.uint8),
        )
        durable = RecordingQueue(capacity=4)
        latest = RecordingMailbox()
        machine = self._ready_machine()
        result = AcquisitionRunner(
            transport=transport,
            parser=_parser(),
            durable_sink=durable,
            latest_mailbox=latest,
            connection=machine,
        ).run(session_id="session-a", target_frames=3)

        self.assertEqual(result.outcome, AcquisitionOutcome.COMPLETED)
        self.assertEqual(result.frames_stored, 3)
        self.assertEqual(machine.state, ConnectionState.READY)
        self.assertEqual(
            events,
            [
                ("durable", 0),
                ("latest", 0),
                ("durable", 1),
                ("latest", 1),
                ("durable", 2),
                ("latest", 2),
            ],
        )
        queued = [durable.get_nowait() for _ in range(3)]
        self.assertEqual([item.session_id for item in queued], ["session-a"] * 3)
        self.assertEqual([item.frame.source_index for item in queued], [0, 1, 2])
        self.assertEqual(latest.read().source_index, 2)
        self.assertEqual(latest.read().host_monotonic_ns, 1_002)

    def test_duration_mode_uses_host_monotonic_frame_span_not_estimated_rate(self) -> None:
        durable = DurableFrameQueue(capacity=4)
        result = AcquisitionRunner(
            transport=SyntheticP4864Transport(
                _profile(),
                realtime=False,
                max_frames=4,
                frame_source=lambda index: np.full((48, 64), index + 1, dtype=np.uint8),
            ),
            parser=_parser(),
            durable_sink=durable,
            latest_mailbox=LatestFrameMailbox(),
            connection=self._ready_machine(),
        ).run(session_id="duration-mode", minimum_duration_ns=2)

        self.assertEqual(result.outcome, AcquisitionOutcome.COMPLETED)
        self.assertEqual(result.frames_stored, 3)
        captured = [durable.get_nowait().frame for _ in range(3)]
        self.assertEqual(
            captured[-1].host_monotonic_ns - captured[0].host_monotonic_ns, 2
        )

    def test_idle_serial_stream_invalidates_instead_of_waiting_forever(self) -> None:
        class SilentTransport:
            def read(self, max_bytes):
                return b""

        clock = iter((0, 1, 3))
        result = AcquisitionRunner(
            transport=SilentTransport(),
            parser=_parser(),
            durable_sink=DurableFrameQueue(capacity=1),
            latest_mailbox=LatestFrameMailbox(),
            connection=self._ready_machine(),
            maximum_idle_read_ns=2,
            monotonic_ns=lambda: next(clock),
        ).run(session_id="idle-stream", target_frames=1)

        self.assertEqual(result.outcome, AcquisitionOutcome.INVALID)
        self.assertEqual(result.frames_stored, 0)
        self.assertIn("idle interval", result.reason or "")

    def test_disconnect_marks_result_incomplete_and_requires_reconnect(self) -> None:
        transport = SyntheticP4864Transport(
            _profile(),
            realtime=False,
            max_frames=9,
            fault_plan=FaultPlan(events={2: (FaultKind.DISCONNECT,)}),
        )
        machine = self._ready_machine()
        result = AcquisitionRunner(
            transport=transport,
            parser=_parser(),
            durable_sink=DurableFrameQueue(capacity=4),
            latest_mailbox=LatestFrameMailbox(),
            connection=machine,
        ).run(session_id="session-disconnect", target_frames=5)

        self.assertEqual(result.outcome, AcquisitionOutcome.INVALID)
        self.assertEqual(result.frames_stored, 2)
        self.assertEqual(machine.state, ConnectionState.INVALID)
        with self.assertRaises(IllegalConnectionTransition):
            machine.start_acquiring()
        machine.start_connecting()
        machine.mark_ready()
        self.assertEqual(machine.state, ConnectionState.READY)

    def test_failed_runner_cannot_stitch_a_reconnected_session(self) -> None:
        machine = self._ready_machine()
        runner = AcquisitionRunner(
            transport=SyntheticP4864Transport(
                _profile(),
                realtime=False,
                max_frames=3,
                fault_plan=FaultPlan(events={0: (FaultKind.DISCONNECT,)}),
            ),
            parser=_parser(),
            durable_sink=DurableFrameQueue(capacity=2),
            latest_mailbox=LatestFrameMailbox(),
            connection=machine,
        )
        first = runner.run(session_id="session-before-reconnect", target_frames=1)
        self.assertEqual(first.outcome, AcquisitionOutcome.INVALID)
        machine.start_connecting()
        machine.mark_ready()

        with self.assertRaisesRegex(RuntimeError, "single-use"):
            runner.run(session_id="session-after-reconnect", target_frames=1)

    def test_storage_failure_never_publishes_unstored_frame(self) -> None:
        class BrokenSink:
            def append(self, session_id, frame, *, timeout=None):
                raise OSError("disk unavailable")

        machine = self._ready_machine()
        latest = LatestFrameMailbox()
        result = AcquisitionRunner(
            transport=SyntheticP4864Transport(
                _profile(), realtime=False, max_frames=1
            ),
            parser=_parser(),
            durable_sink=BrokenSink(),
            latest_mailbox=latest,
            connection=machine,
        ).run(session_id="session-storage-failure", target_frames=1)

        self.assertEqual(result.outcome, AcquisitionOutcome.INVALID)
        self.assertEqual(result.frames_stored, 0)
        self.assertIsNone(latest.read())
        self.assertEqual(machine.state, ConnectionState.INVALID)

    def test_full_durable_queue_times_out_and_invalidates_without_silent_drop(self) -> None:
        machine = self._ready_machine()
        queue = DurableFrameQueue(capacity=1)
        result = AcquisitionRunner(
            transport=SyntheticP4864Transport(
                _profile(), realtime=False, max_frames=2
            ),
            parser=_parser(),
            durable_sink=queue,
            latest_mailbox=LatestFrameMailbox(),
            connection=machine,
            storage_append_timeout_s=0.0,
        ).run(session_id="session-full-queue", target_frames=2)

        self.assertEqual(result.outcome, AcquisitionOutcome.INVALID)
        self.assertEqual(result.frames_stored, 1)
        self.assertIn("storage handoff failed", result.reason or "")
        self.assertEqual(machine.state, ConnectionState.INVALID)

    def test_parser_resynchronization_invalidates_and_discards_the_active_session(self) -> None:
        class DiscardingSink:
            def __init__(self) -> None:
                self.frames: list[int] = []
                self.reason: str | None = None

            def append(self, session_id, frame, *, timeout=None):
                self.frames.append(frame.source_index)

            def discard(self, *, reason: str) -> None:
                self.reason = reason

        sink = DiscardingSink()
        machine = self._ready_machine()
        result = AcquisitionRunner(
            transport=SyntheticP4864Transport(
                _profile(),
                realtime=False,
                max_frames=3,
                fault_plan=FaultPlan(events={1: (FaultKind.BAD_TAIL,)}),
            ),
            parser=_parser(),
            durable_sink=sink,
            latest_mailbox=LatestFrameMailbox(),
            connection=machine,
        ).run(session_id="session-resync", target_frames=3)

        self.assertEqual(result.outcome, AcquisitionOutcome.INVALID)
        self.assertEqual(sink.frames, [0])
        self.assertIn("resynchronization", sink.reason)
        self.assertEqual(machine.state, ConnectionState.INVALID)

    def test_worker_executes_blocking_reader_outside_calling_thread(self) -> None:
        caller_thread = threading.get_ident()
        observed_threads: list[int] = []

        class ThreadRecordingQueue(DurableFrameQueue):
            def append(self, session_id, frame, *, timeout=None):
                observed_threads.append(threading.get_ident())
                super().append(session_id, frame, timeout=timeout)

        runner = AcquisitionRunner(
            transport=SyntheticP4864Transport(
                _profile(), realtime=False, max_frames=1
            ),
            parser=_parser(),
            durable_sink=ThreadRecordingQueue(capacity=2),
            latest_mailbox=LatestFrameMailbox(),
            connection=self._ready_machine(),
        )
        worker = AcquisitionWorker(runner)

        worker.start(session_id="session-worker", target_frames=1)
        result = worker.join(timeout=2.0)

        self.assertEqual(result.outcome, AcquisitionOutcome.COMPLETED)
        self.assertEqual(len(observed_threads), 1)
        self.assertNotEqual(observed_threads[0], caller_thread)


if __name__ == "__main__":
    unittest.main()
