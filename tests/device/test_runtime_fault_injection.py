from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import numpy as np

from client.device.acquisition import ConnectionStateMachine, LatestFrameMailbox
from client.device.protocol import DaoOneP4864Parser, ProtocolProfile
from client.device.session_runtime import HardwareSessionRuntime, QualityDecision, SessionValidity
from client.device.simulator import FaultKind, FaultPlan, SyntheticP4864Transport
from client.spool.session_commit import ValidSessionStager
from client.spool.state_store import SensitiveBlobCodec, StateStore


class _Key:
    def get_key(self) -> bytes:
        return b"f" * 32


def _profile() -> ProtocolProfile:
    return ProtocolProfile.synthetic(
        version="runtime-fault-injection/1",
        length_byte_order="little",
        checksum_start=0,
        checksum_end=3077,
    )


def _ready() -> ConnectionStateMachine:
    connection = ConnectionStateMachine()
    connection.start_connecting()
    connection.mark_ready()
    return connection


class RuntimeFaultInjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.store = StateStore(self.root / "state.sqlite3", SensitiveBlobCodec(_Key()))
        self.store.put_subject_ref("subject", b"opaque")

    def tearDown(self) -> None:
        self.store.close()
        self.directory.cleanup()

    def _runtime(
        self,
        *,
        session_id: str,
        transport: SyntheticP4864Transport,
        parser: DaoOneP4864Parser,
    ) -> HardwareSessionRuntime:
        stager = ValidSessionStager(
            self.root / "data",
            session_id=session_id,
            key_provider=_Key(),
            store=self.store,
            subject_uuid="subject",
            consent_id=None,
            versions={"protocol": "runtime-fault-injection/1", "quality": "test/1"},
            started_at_ns=0,
        )
        return HardwareSessionRuntime(
            transport=transport,
            parser=parser,
            connection=_ready(),
            mailbox=LatestFrameMailbox(),
            stager=stager,
            quality_gate=type(
                "Gate",
                (),
                {
                    "evaluate": lambda _, *, session_id, frames: QualityDecision(
                        SessionValidity.VALID
                    )
                },
            )(),
            wall_time_ns=lambda: 10,
        )

    def _assert_no_formal_session(self, session_id: str) -> None:
        self.assertFalse((self.root / "data" / ".staging" / session_id).exists())
        self.assertFalse((self.root / "data" / "sessions" / session_id).exists())
        with self.assertRaises(KeyError):
            self.store.session_status(session_id)

    def test_short_wire_integrity_fault_is_committed_with_an_audit_record(self) -> None:
        session_id = "bad-tail"
        transport = SyntheticP4864Transport(
            _profile(),
            realtime=False,
            max_frames=4,
            fault_plan=FaultPlan(events={1: (FaultKind.BAD_TAIL,)}),
            frame_source=lambda index: np.full((48, 64), 10 + index, dtype=np.uint8),
        )
        result = self._runtime(
            session_id=session_id,
            transport=transport,
            parser=DaoOneP4864Parser(
                _profile(),
                allow_unverified=True,
                monotonic_ns=iter(range(10_000, 100_000, 100)).__next__,
                wall_time_ns=lambda: 2_000,
            ),
        ).capture(session_id=session_id, target_frames=3)

        self.assertEqual(result.validity, SessionValidity.VALID)
        self.assertTrue(result.committed)
        self.assertEqual(result.acquisition.frames_stored, 3)
        self.assertEqual(len(result.acquisition.integrity_events), 1)
        self.assertEqual(result.acquisition.integrity_events[0].failure_kind, "TAIL")
        self.assertEqual(len(result.acquisition.reconstructed_frames), 1)
        self.assertEqual(self.store.session_status(session_id), ("CLOSED", "VALID", 10))

    def test_disconnect_after_a_frame_invalidates_and_discards_the_whole_session(self) -> None:
        session_id = "disconnect"
        transport = SyntheticP4864Transport(
            _profile(),
            realtime=False,
            max_frames=2,
            fault_plan=FaultPlan(events={1: (FaultKind.DISCONNECT,)}),
            frame_source=lambda _: np.full((48, 64), 10, dtype=np.uint8),
        )
        result = self._runtime(
            session_id=session_id,
            transport=transport,
            parser=DaoOneP4864Parser(_profile(), allow_unverified=True),
        ).capture(session_id=session_id, target_frames=2)

        self.assertEqual(result.validity, SessionValidity.INVALID)
        self.assertIn("transport disconnected", result.reason or "")
        self._assert_no_formal_session(session_id)

    def test_long_arrival_interval_invalidates_and_discards_the_whole_session(self) -> None:
        class FakeClock:
            def __init__(self) -> None:
                self.now_ns = 0

            def monotonic_ns(self) -> int:
                return self.now_ns

            def sleep(self, seconds: float) -> None:
                self.now_ns += round(seconds * 1_000_000_000)

        clock = FakeClock()
        session_id = "long-gap"
        transport = SyntheticP4864Transport(
            _profile(),
            realtime=True,
            rate_hz=10.0,
            max_frames=3,
            monotonic_ns=clock.monotonic_ns,
            sleep=clock.sleep,
            fault_plan=FaultPlan(
                events={1: (FaultKind.LONG_INTERVAL,)}, long_interval_multiplier=60.0
            ),
            frame_source=lambda _: np.full((48, 64), 10, dtype=np.uint8),
        )
        result = self._runtime(
            session_id=session_id,
            transport=transport,
            parser=DaoOneP4864Parser(
                _profile(),
                allow_unverified=True,
                monotonic_ns=clock.monotonic_ns,
                wall_time_ns=lambda: 1,
            ),
        ).capture(session_id=session_id, target_frames=3)

        self.assertEqual(result.validity, SessionValidity.INVALID)
        self.assertIn("no valid decoded signal for five seconds", result.reason or "")
        self._assert_no_formal_session(session_id)


if __name__ == "__main__":
    unittest.main()
