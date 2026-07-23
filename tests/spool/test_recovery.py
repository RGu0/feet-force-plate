import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from client.spool.recovery import (
    RecoveryScanner,
    cleanup_acknowledged_segments,
    seal_and_register,
)
from client.spool.segments import ImmutableSegmentWriter
from client.spool.state_store import SensitiveBlobCodec, StateStore
from tests.spool.test_segments import StaticKeyProvider, _frame


class RecoveryScannerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.keys = StaticKeyProvider()
        self.store = StateStore(
            self.root / "state.sqlite3", SensitiveBlobCodec(self.keys)
        )
        self.store.put_subject_ref("subject", b"opaque")
        self.store.create_session(
            "session-1",
            subject_uuid="subject",
            consent_id=None,
            lifecycle_status="ACQUIRING",
            versions_json=b"{}",
            started_at_ns=0,
        )

    def tearDown(self) -> None:
        self.store.close()
        self.directory.cleanup()

    def _writer(self) -> ImmutableSegmentWriter:
        writer = ImmutableSegmentWriter(
            self.root / "segments",
            session_id="session-1",
            key_provider=self.keys,
            versions={"schema": "raw-frame/1"},
            segment_duration_seconds=5.0,
        )
        writer.append(_frame(0))
        return writer

    def test_sealed_file_is_registered_before_pending_upload_is_visible(self) -> None:
        sealed = seal_and_register(self._writer(), self.store, self.root)

        self.assertEqual(self.store.segment_state(sealed.segment_id), "SEALED")
        self.assertEqual(
            self.store.upload_tasks_for_segment(sealed.segment_id), ["PENDING"]
        )

    def test_crash_after_rename_before_database_is_recovered_idempotently(self) -> None:
        sealed = self._writer().close()
        self.assertFalse(self.store.segment_exists(sealed.segment_id))
        scanner = RecoveryScanner(
            self.root / "segments", self.store, self.keys, self.root
        )

        first = scanner.scan(recovered_at_ns=100)
        second = scanner.scan(recovered_at_ns=101)

        self.assertEqual(first.orphan_segments_registered, 1)
        self.assertEqual(second.orphan_segments_registered, 0)
        self.assertEqual(self.store.segment_state(sealed.segment_id), "SEALED")
        self.assertEqual(
            self.store.upload_tasks_for_segment(sealed.segment_id), ["PENDING"]
        )

    def test_complete_temp_segment_is_promoted_and_registered_after_restart(self) -> None:
        sealed = self._writer().close()
        temporary = sealed.path.with_suffix(".tmp")
        sealed.path.replace(temporary)
        scanner = RecoveryScanner(
            self.root / "segments", self.store, self.keys, self.root
        )

        result = scanner.scan(recovered_at_ns=100)

        self.assertEqual(result.temporary_recovered, 1)
        self.assertFalse(temporary.exists())
        self.assertTrue(sealed.path.exists())
        self.assertEqual(self.store.segment_state(sealed.segment_id), "SEALED")

    def test_invalid_tmp_is_quarantined_and_never_registered(self) -> None:
        session_dir = self.root / "segments" / "session-1"
        session_dir.mkdir(parents=True)
        temporary = session_dir / "broken.tmp"
        temporary.write_bytes(b"partial ciphertext")
        scanner = RecoveryScanner(
            self.root / "segments", self.store, self.keys, self.root
        )

        result = scanner.scan(recovered_at_ns=100)

        self.assertEqual(result.temporary_quarantined, 1)
        self.assertFalse(temporary.exists())
        self.assertTrue((session_dir / "quarantine" / "broken.tmp.corrupt").exists())

    def test_tampered_sealed_file_is_quarantined_without_stopping_recovery(self) -> None:
        sealed = seal_and_register(self._writer(), self.store, self.root)
        payload = bytearray(sealed.path.read_bytes())
        payload[len(payload) // 2] ^= 1
        sealed.path.write_bytes(payload)
        scanner = RecoveryScanner(
            self.root / "segments", self.store, self.keys, self.root
        )

        result = scanner.scan(recovered_at_ns=100)

        self.assertEqual(result.sealed_quarantined, 1)
        self.assertFalse(sealed.path.exists())
        self.assertEqual(self.store.segment_state(sealed.segment_id), "CORRUPT")
        self.assertEqual(
            self.store.upload_tasks_for_segment(sealed.segment_id), ["QUARANTINED"]
        )
        self.assertTrue(
            (sealed.path.parent / "quarantine" / f"{sealed.path.name}.corrupt").exists()
        )

    def test_acknowledged_file_is_retained_when_automatic_cleanup_runs(self) -> None:
        relative_path = "segments/session-1/eligible.ffps"
        file_path = self.root / relative_path
        file_path.parent.mkdir(parents=True)
        file_path.write_bytes(b"acknowledged encrypted bytes")
        self.store.add_segment(
            "eligible",
            session_id="session-1",
            relative_path=relative_path,
            byte_count=file_path.stat().st_size,
            state="ACKNOWLEDGED",
            sealed_at_ns=1,
            acknowledged_at_ns=2,
            retain_until_ns=50,
        )

        result = cleanup_acknowledged_segments(self.store, self.root, now_ns=100)

        self.assertEqual(result.files_deleted, 0)
        self.assertEqual(result.records_finalized, 0)
        self.assertTrue(file_path.exists())
        self.assertTrue(self.store.segment_exists("eligible"))

    def test_cleanup_noop_does_not_touch_acknowledged_file(self) -> None:
        relative_path = "segments/session-1/eligible.ffps"
        file_path = self.root / relative_path
        file_path.parent.mkdir(parents=True)
        file_path.write_bytes(b"acknowledged encrypted bytes")
        self.store.add_segment(
            "eligible",
            session_id="session-1",
            relative_path=relative_path,
            byte_count=file_path.stat().st_size,
            state="ACKNOWLEDGED",
            sealed_at_ns=1,
            acknowledged_at_ns=2,
            retain_until_ns=50,
        )

        result = cleanup_acknowledged_segments(self.store, self.root, now_ns=100)

        self.assertEqual(result, type(result)())
        self.assertTrue(file_path.exists())
        self.assertTrue(self.store.segment_exists("eligible"))


if __name__ == "__main__":
    unittest.main()
