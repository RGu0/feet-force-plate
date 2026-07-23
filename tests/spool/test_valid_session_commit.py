import tempfile
from pathlib import Path
import unittest

import numpy as np

from client.device.protocol import RawFrame
from client.spool.session_commit import ValidSessionStager
from client.spool.state_store import SensitiveBlobCodec, StateStore


class StaticKeyProvider:
    def get_key(self) -> bytes:
        return b"v" * 32


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


class ValidSessionStagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.keys = StaticKeyProvider()
        self.store = StateStore(
            self.root / "state.sqlite3", SensitiveBlobCodec(self.keys)
        )
        self.store.put_subject_ref("subject-1", b"opaque")

    def tearDown(self) -> None:
        self.store.close()
        self.directory.cleanup()

    def _stager(self, session_id: str) -> ValidSessionStager:
        return ValidSessionStager(
            self.root / "data",
            session_id=session_id,
            key_provider=self.keys,
            store=self.store,
            subject_uuid="subject-1",
            consent_id=None,
            versions={"protocol": "observed-compact/1", "quality": "mvp/1"},
            started_at_ns=1_000_000_000,
        )

    def test_invalid_capture_discards_all_temporary_raw_data_and_creates_no_session(self) -> None:
        stager = self._stager("invalid")
        stager.append(_frame(0))
        stager.discard(reason="PARSER_RESYNC")

        self.assertFalse((self.root / "data" / ".staging" / "invalid").exists())
        self.assertFalse((self.root / "data" / "sessions" / "invalid").exists())
        with self.assertRaises(KeyError):
            self.store.session_status("invalid")

    def test_valid_capture_is_promoted_then_registered_with_ready_network_handoff(self) -> None:
        stager = self._stager("valid")
        stager.append(_frame(0))
        committed = stager.commit_valid(ended_at_ns=1_100_000_000)

        self.assertFalse((self.root / "data" / ".staging" / "valid").exists())
        self.assertTrue((self.root / "data" / "sessions" / "valid" / "manifest.json").exists())
        self.assertEqual(self.store.session_status("valid"), ("CLOSED", "VALID", 1_100_000_000))
        self.assertEqual(committed.total_frames, 1)
        self.assertEqual(self.store.sync_handoff_state("valid"), "READY_FOR_NETWORK")

    def test_interrupted_staging_is_deleted_on_startup_recovery(self) -> None:
        stager = self._stager("interrupted")
        for index in range(101):
            stager.append(_frame(index))

        removed = ValidSessionStager.discard_interrupted_staging(self.root / "data")

        self.assertEqual(removed, 1)
        self.assertFalse((self.root / "data" / ".staging" / "interrupted").exists())
        with self.assertRaises(KeyError):
            self.store.session_status("interrupted")


if __name__ == "__main__":
    unittest.main()
