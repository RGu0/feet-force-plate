import importlib
import random
import unittest

import numpy as np


def _synthetic_profile(protocol: object):
    return protocol.ProtocolProfile.synthetic(
        version="do-p4864/synthetic-test-1",
        length_byte_order="little",
        checksum_start=0,
        checksum_end=3077,
    )


def _frame_bytes(protocol: object, profile: object, values: np.ndarray) -> bytes:
    payload = np.asarray(values, dtype=np.uint8).reshape(48, 64).tobytes(order="F")
    frame = bytearray(b"\xff\xaa")
    frame.extend(protocol.FRAME_LENGTH.to_bytes(2, profile.length_byte_order))
    frame.append(0x01)
    frame.extend(payload)
    frame.append((-sum(frame[profile.checksum_start : profile.checksum_end])) & 0xFF)
    frame.append(0xFA)
    return bytes(frame)


class ProtocolSurfaceTests(unittest.TestCase):
    def test_current_runtime_contract_has_no_legacy_6151_byte_definition(self) -> None:
        protocol = importlib.import_module("client.device.protocol")

        self.assertEqual(protocol.FRAME_LENGTH, 3079)
        self.assertEqual(protocol.CHECKSUM_OFFSET, 3077)
        self.assertEqual(protocol.TAIL_OFFSET, 3078)
        self.assertFalse(hasattr(protocol, "COMPACT_OBSERVED_FRAME_LENGTH"))
        self.assertEqual(
            tuple(protocol.PayloadEncoding), (protocol.PayloadEncoding.UINT8_RAW,)
        )

    def test_observed_compact_profile_decodes_8bit_grid_without_checksum_filter(self) -> None:
        protocol = importlib.import_module("client.device.protocol")
        profile = protocol.ProtocolProfile.observed_compact_8bit(
            version="do-p4864/observed-compact-test-1"
        )
        values = np.arange(48 * 64, dtype=np.uint8).reshape(48, 64)
        wire_frame = b"".join(
            (
                b"\xff\xaa\x0c\x07\x01",
                values.tobytes(order="F"),
                b"\x01",  # Deliberately differs from the documented checksum rule.
                b"\xfa",
            )
        )

        parser = protocol.DaoOneP4864Parser(profile)
        decoded = []
        for chunk in (wire_frame[:7], wire_frame[7:2050], wire_frame[2050:]):
            decoded.extend(parser.feed(chunk))

        self.assertEqual(len(wire_frame), 3079)
        self.assertEqual(len(decoded), 1)
        np.testing.assert_array_equal(decoded[0].values, values)
        self.assertEqual(wire_frame[5:53], values[:, 0].tobytes())
        self.assertEqual(decoded[0].values.dtype, np.dtype("uint8"))
        self.assertFalse(decoded[0].values.flags.writeable)
        self.assertNotIn("PROTOCOL_PROFILE_UNVERIFIED", decoded[0].quality_flags)
        self.assertIn("CHECKSUM_NOT_ENFORCED", decoded[0].quality_flags)
        self.assertIn("CHECKSUM_MISMATCH_OBSERVED", decoded[0].quality_flags)
        self.assertEqual(parser.statistics.checksum_failures, 0)
        self.assertEqual(parser.statistics.checksum_observations, 1)
        self.assertEqual(parser.statistics.checksum_mismatches, 1)
        self.assertEqual(parser.statistics.length_observations, 1)
        self.assertEqual(parser.statistics.length_mismatches, 0)

    def test_observed_compact_profile_rejects_length_candidate_mismatch_and_recovers(self) -> None:
        protocol = importlib.import_module("client.device.protocol")
        profile = protocol.ProtocolProfile.observed_compact_8bit(
            version="do-p4864/observed-length-audit-test-1"
        )
        values = np.full((48, 64), 0x2A, dtype=np.uint8)
        invalid = b"".join(
            (
                b"\xff\xaa\x00\x00\x01",
                values.tobytes(order="F"),
                b"\x01",
                b"\xfa",
            )
        )

        valid = _frame_bytes(protocol, profile, values)
        parser = protocol.DaoOneP4864Parser(profile)
        decoded = parser.feed(invalid + valid)

        self.assertEqual(len(decoded), 1)
        np.testing.assert_array_equal(decoded[0].values, values)
        self.assertEqual(parser.statistics.length_observations, 2)
        self.assertEqual(parser.statistics.length_mismatches, 1)
        self.assertEqual(parser.statistics.length_failures, 1)
        self.assertEqual(parser.statistics.invalid_frames, 1)

    def test_protocol_module_exposes_incremental_parser(self) -> None:
        try:
            protocol = importlib.import_module("client.device.protocol")
        except ModuleNotFoundError as exc:
            self.fail(f"protocol module is missing: {exc}")

        self.assertTrue(hasattr(protocol, "DaoOneP4864Parser"))

    def test_parser_rejects_synthetic_profile_without_explicit_override(self) -> None:
        protocol = importlib.import_module("client.device.protocol")
        profile_type = getattr(protocol, "ProtocolProfile", None)
        error_type = getattr(protocol, "UnverifiedProtocolProfileError", None)
        self.assertIsNotNone(profile_type)
        self.assertIsNotNone(error_type)

        profile = profile_type.synthetic(
            version="do-p4864/synthetic-test-1",
            length_byte_order="little",
            checksum_start=0,
            checksum_end=3077,
        )
        with self.assertRaises(error_type):
            protocol.DaoOneP4864Parser(profile)

    def test_capture_verified_profile_requires_fixture_digest(self) -> None:
        protocol = importlib.import_module("client.device.protocol")
        profile_type = protocol.ProtocolProfile
        self.assertTrue(hasattr(profile_type, "capture_verified"))

        with self.assertRaises(ValueError):
            profile_type.capture_verified(
                version="do-p4864/capture-1",
                length_byte_order="little",
                checksum_start=0,
                checksum_end=3077,
                fixture_sha256="not-a-sha256",
            )

    def test_direct_verified_profile_cannot_bypass_fixture_digest_gate(self) -> None:
        protocol = importlib.import_module("client.device.protocol")

        with self.assertRaises(ValueError):
            protocol.ProtocolProfile(
                version="do-p4864/unsafe-direct-construction",
                length_byte_order="little",
                checksum_start=0,
                checksum_end=3077,
                evidence=protocol.ProfileEvidence.CAPTURE_VERIFIED,
                fixture_sha256=None,
            )

    def test_parser_accepts_single_bytes_and_emits_host_audited_matrix(self) -> None:
        protocol = importlib.import_module("client.device.protocol")
        profile = _synthetic_profile(protocol)
        source = np.arange(3072, dtype=np.uint8).reshape(48, 64)
        wire_frame = _frame_bytes(protocol, profile, source)
        monotonic_values = iter([123_456_789])
        wall_values = iter([987_654_321])
        try:
            parser = protocol.DaoOneP4864Parser(
                profile,
                allow_unverified=True,
                monotonic_ns=lambda: next(monotonic_values),
                wall_time_ns=lambda: next(wall_values),
            )
        except TypeError as exc:
            self.fail(f"parser clock injection is missing: {exc}")

        decoded = []
        for byte in wire_frame:
            decoded.extend(parser.feed(bytes([byte])))

        self.assertEqual(len(decoded), 1)
        frame = decoded[0]
        np.testing.assert_array_equal(frame.values, source)
        self.assertEqual(frame.values.shape, (48, 64))
        self.assertEqual(frame.values.dtype, np.dtype("uint8"))
        self.assertFalse(frame.values.flags.writeable)
        self.assertEqual(frame.source_index, 0)
        self.assertEqual(frame.host_monotonic_ns, 123_456_789)
        self.assertEqual(frame.host_wall_time_ns, 987_654_321)
        self.assertIsNone(frame.device_frame_seq)
        self.assertIsNone(frame.device_timestamp_ns)
        self.assertIn("PROTOCOL_PROFILE_UNVERIFIED", frame.quality_flags)

    def test_random_chunks_and_sticky_frames_preserve_order_and_interval_audit(self) -> None:
        protocol = importlib.import_module("client.device.protocol")
        profile = _synthetic_profile(protocol)
        first = _frame_bytes(protocol, profile, np.zeros((48, 64), dtype=np.uint8))
        second = _frame_bytes(protocol, profile, np.ones((48, 64), dtype=np.uint8))
        ticks = iter([1_000_000_000, 1_083_000_000])
        parser = protocol.DaoOneP4864Parser(
            profile,
            allow_unverified=True,
            monotonic_ns=lambda: next(ticks),
            wall_time_ns=lambda: 55,
        )
        stream = first + second
        rng = random.Random(81)
        cursor = 0
        decoded = []
        while cursor < len(stream):
            width = rng.randint(1, 997)
            decoded.extend(parser.feed(stream[cursor : cursor + width]))
            cursor += width

        self.assertEqual([frame.source_index for frame in decoded], [0, 1])
        np.testing.assert_array_equal(decoded[0].values, 0)
        np.testing.assert_array_equal(decoded[1].values, 1)
        stats = getattr(parser, "statistics", None)
        self.assertIsNotNone(stats)
        self.assertEqual(stats.bytes_received, len(stream))
        self.assertEqual(stats.valid_frames, 2)
        self.assertEqual(stats.interval_count, 1)
        self.assertEqual(stats.interval_min_ns, 83_000_000)
        self.assertEqual(stats.interval_max_ns, 83_000_000)

    def test_noise_and_bad_checksum_resynchronize_at_next_header(self) -> None:
        protocol = importlib.import_module("client.device.protocol")
        profile = _synthetic_profile(protocol)
        valid = _frame_bytes(protocol, profile, np.full((48, 64), 7, dtype=np.uint8))
        corrupt = bytearray(valid)
        corrupt[protocol.CHECKSUM_OFFSET] ^= 0x01
        parser = protocol.DaoOneP4864Parser(
            profile,
            allow_unverified=True,
            monotonic_ns=lambda: 1,
            wall_time_ns=lambda: 2,
        )

        decoded = parser.feed(b"serial-noise" + bytes(corrupt) + valid)

        self.assertEqual(len(decoded), 1)
        np.testing.assert_array_equal(decoded[0].values, 7)
        self.assertEqual(parser.statistics.valid_frames, 1)
        self.assertEqual(parser.statistics.invalid_frames, 1)
        self.assertEqual(parser.statistics.checksum_failures, 1)
        self.assertGreaterEqual(parser.statistics.resynchronizations, 2)
        self.assertGreaterEqual(parser.statistics.discarded_bytes, len(b"serial-noise") + len(corrupt))

    def test_sustained_noise_never_retains_more_than_configured_buffer_limit(self) -> None:
        protocol = importlib.import_module("client.device.protocol")
        profile = _synthetic_profile(protocol)
        limit = protocol.FRAME_LENGTH + 32
        try:
            parser = protocol.DaoOneP4864Parser(
                profile,
                allow_unverified=True,
                max_buffer_bytes=limit,
            )
        except TypeError as exc:
            self.fail(f"bounded-buffer configuration is missing: {exc}")

        self.assertEqual(parser.feed(b"\x11" * (limit * 20)), [])
        self.assertLessEqual(parser.buffered_bytes, limit)
        self.assertLessEqual(parser.statistics.peak_buffer_bytes, limit)

    def test_length_function_and_tail_failures_are_audited_separately(self) -> None:
        protocol = importlib.import_module("client.device.protocol")
        profile = _synthetic_profile(protocol)
        valid = _frame_bytes(protocol, profile, np.zeros((48, 64), dtype=np.uint8))
        bad_length = bytearray(valid)
        bad_length[2:4] = b"\x00\x00"
        bad_function = bytearray(valid)
        bad_function[protocol.FUNCTION_OFFSET] = 0x02
        bad_tail = bytearray(valid)
        bad_tail[protocol.TAIL_OFFSET] = 0x00
        parser = protocol.DaoOneP4864Parser(profile, allow_unverified=True)

        decoded = parser.feed(bytes(bad_length + bad_function + bad_tail) + valid)

        self.assertEqual(len(decoded), 1)
        self.assertEqual(parser.statistics.invalid_frames, 3)
        self.assertEqual(getattr(parser.statistics, "length_failures", None), 1)
        self.assertEqual(getattr(parser.statistics, "function_failures", None), 1)
        self.assertEqual(getattr(parser.statistics, "tail_failures", None), 1)
        self.assertEqual(parser.statistics.checksum_failures, 0)

    def test_capture_profile_controls_wire_length_order_and_checksum_slice(self) -> None:
        protocol = importlib.import_module("client.device.protocol")
        profile = protocol.ProtocolProfile.capture_verified(
            version="do-p4864/capture-contract-test-1",
            length_byte_order="big",
            checksum_start=5,
            checksum_end=3077,
            fixture_sha256="a" * 64,
        )
        wire_frame = _frame_bytes(
            protocol, profile, np.full((48, 64), 0x23, dtype=np.uint8)
        )

        decoded = protocol.DaoOneP4864Parser(profile).feed(wire_frame)

        self.assertEqual(wire_frame[2:4], b"\x0c\x07")
        self.assertEqual(len(decoded), 1)
        np.testing.assert_array_equal(decoded[0].values, 0x23)
        self.assertNotIn("PROTOCOL_PROFILE_UNVERIFIED", decoded[0].quality_flags)

    def test_seeded_noise_fuzz_recovers_all_inserted_valid_frames(self) -> None:
        protocol = importlib.import_module("client.device.protocol")
        profile = _synthetic_profile(protocol)
        rng = random.Random(810082)
        stream = bytearray()
        expected_markers: list[int] = []
        for marker in range(1, 41):
            stream.extend(rng.randbytes(rng.randint(0, 7_000)))
            expected_markers.append(marker)
            stream.extend(
                _frame_bytes(
                    protocol,
                    profile,
                    np.full((48, 64), marker, dtype=np.uint8),
                )
            )
        parser = protocol.DaoOneP4864Parser(profile, allow_unverified=True)
        decoded = []
        cursor = 0
        while cursor < len(stream):
            width = rng.randint(1, 10_000)
            decoded.extend(parser.feed(stream[cursor : cursor + width]))
            cursor += width

        self.assertEqual(
            [int(frame.values[0, 0]) for frame in decoded], expected_markers
        )
        self.assertEqual(parser.statistics.valid_frames, len(expected_markers))
        self.assertLessEqual(parser.buffered_bytes, protocol.FRAME_LENGTH * 2)


if __name__ == "__main__":
    unittest.main()
