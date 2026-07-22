import tempfile
from pathlib import Path
import unittest

import numpy as np

from client.device.protocol import RawFrame
from client.spool.segments import (
    ImmutableSegmentWriter,
    SegmentIntegrityError,
    read_segment,
    write_session_manifest,
)


class StaticKeyProvider:
    def get_key(self) -> bytes:
        return b"s" * 32


def _frame(index: int, *, dtype: np.dtype = np.dtype(np.uint16)) -> RawFrame:
    values = np.full((48, 64), index, dtype=dtype)
    values.setflags(write=False)
    return RawFrame(
        values=values,
        host_monotonic_ns=index * 1_000_000_000 // 12,
        host_wall_time_ns=1_000_000_000 + index * 1_000_000_000 // 12,
        source_index=index,
        device_frame_seq=None,
        device_timestamp_ns=None,
        quality_flags=frozenset({"SYNTHETIC"}),
    )


class ImmutableSegmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_five_second_boundary_seals_encrypted_immutable_raw_frames(self) -> None:
        writer = ImmutableSegmentWriter(
            self.root,
            session_id="session-1",
            key_provider=StaticKeyProvider(),
            versions={"schema": "raw-frame/1", "protocol": "fixture-pending"},
            segment_duration_seconds=5.0,
            target_plaintext_bytes=10_000_000,
        )
        sealed = None
        for index in range(61):
            sealed = writer.append(_frame(index)) or sealed

        self.assertIsNotNone(sealed)
        self.assertFalse(sealed.path.name.endswith(".tmp"))
        self.assertEqual(sealed.frame_count, 61)
        self.assertEqual(sealed.first_source_index, 0)
        self.assertEqual(sealed.last_source_index, 60)
        restored = read_segment(sealed.path, StaticKeyProvider())
        self.assertEqual([frame.source_index for frame in restored.frames], list(range(61)))
        np.testing.assert_array_equal(restored.frames[37].values, 37)
        self.assertEqual(restored.versions["protocol"], "fixture-pending")
        self.assertIn("SYNTHETIC", restored.quality_flags)

    def test_random_nonce_makes_identical_plaintext_ciphertexts_distinct(self) -> None:
        outputs = []
        for session_id in ("session-a", "session-b"):
            writer = ImmutableSegmentWriter(
                self.root,
                session_id=session_id,
                key_provider=StaticKeyProvider(),
                versions={"schema": "raw-frame/1"},
                segment_duration_seconds=5.0,
            )
            writer.append(_frame(0))
            outputs.append(writer.close())

        self.assertNotEqual(outputs[0].nonce, outputs[1].nonce)
        self.assertNotEqual(outputs[0].ciphertext_sha256, outputs[1].ciphertext_sha256)

    def test_observed_compact_uint8_frame_round_trips_without_dtype_promotion(self) -> None:
        writer = ImmutableSegmentWriter(
            self.root,
            session_id="session-observed-u8",
            key_provider=StaticKeyProvider(),
            versions={"schema": "raw-frame/1", "protocol": "observed-compact"},
            segment_duration_seconds=5.0,
        )
        observed = _frame(173, dtype=np.dtype(np.uint8))
        writer.append(observed)
        sealed = writer.close()

        restored = read_segment(sealed.path, StaticKeyProvider()).frames[0]
        self.assertEqual(restored.values.dtype, np.dtype(np.uint8))
        np.testing.assert_array_equal(restored.values, observed.values)

    def test_tamper_is_detected_before_plaintext_is_returned(self) -> None:
        writer = ImmutableSegmentWriter(
            self.root,
            session_id="session-tamper",
            key_provider=StaticKeyProvider(),
            versions={"schema": "raw-frame/1"},
            segment_duration_seconds=5.0,
        )
        writer.append(_frame(0))
        sealed = writer.close()
        payload = bytearray(sealed.path.read_bytes())
        payload[len(payload) // 2] ^= 1
        sealed.path.write_bytes(payload)

        with self.assertRaises(SegmentIntegrityError):
            read_segment(sealed.path, StaticKeyProvider())

    def test_session_manifest_binds_segment_index_digest_frames_versions_and_quality(self) -> None:
        writer = ImmutableSegmentWriter(
            self.root,
            session_id="session-manifest",
            key_provider=StaticKeyProvider(),
            versions={"schema": "raw-frame/1", "mode": "SCREENING"},
            segment_duration_seconds=5.0,
        )
        writer.append(_frame(0))
        sealed = writer.close()

        manifest = write_session_manifest(
            self.root,
            session_id="session-manifest",
            segment_paths=[sealed.path],
            key_provider=StaticKeyProvider(),
            local_quality_outcome="AUTOMATIC_SYNTHETIC_PASS",
        )

        self.assertEqual(manifest["total_frames"], 1)
        self.assertEqual(manifest["segments"][0]["segment_index"], 0)
        self.assertEqual(
            manifest["segments"][0]["ciphertext_sha256"],
            sealed.ciphertext_sha256,
        )
        self.assertEqual(manifest["versions"]["mode"], "SCREENING")
        self.assertEqual(manifest["local_quality_outcome"], "AUTOMATIC_SYNTHETIC_PASS")
        self.assertEqual(len(manifest["manifest_sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
