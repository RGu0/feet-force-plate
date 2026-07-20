import importlib
import hashlib
from pathlib import Path
import tempfile
import unittest

import numpy as np

from client.device.protocol import DaoOneP4864Parser, ProtocolProfile
from client.device.transport import ByteTransport, TransportDisconnected


def _profile() -> ProtocolProfile:
    return ProtocolProfile.synthetic(
        version="do-p4864/synthetic-simulator-test-1",
        length_byte_order="little",
        checksum_start=0,
        checksum_end=6149,
    )


class SimulatorFrameTests(unittest.TestCase):
    def test_encoded_matrix_traverses_the_real_parser(self) -> None:
        try:
            simulator = importlib.import_module("client.device.simulator")
        except ModuleNotFoundError as exc:
            self.fail(f"simulator module is missing: {exc}")
        self.assertTrue(hasattr(simulator, "encode_frame"))
        values = np.arange(3072, dtype=np.uint16).reshape(48, 64)

        wire = simulator.encode_frame(values, _profile())
        decoded = DaoOneP4864Parser(_profile(), allow_unverified=True).feed(wire)

        self.assertEqual(len(wire), 6151)
        self.assertEqual(len(decoded), 1)
        np.testing.assert_array_equal(decoded[0].values, values)

    def test_encoder_rejects_counts_outside_12_bit_range(self) -> None:
        simulator = importlib.import_module("client.device.simulator")

        with self.assertRaises(ValueError):
            simulator.encode_frame(
                np.full((48, 64), 4096, dtype=np.uint16), _profile()
            )

    def test_pressure_scene_models_static_and_left_right_load_bias(self) -> None:
        simulator = importlib.import_module("client.device.simulator")
        scene_type = getattr(simulator, "PressureScene", None)
        pattern_type = getattr(simulator, "PressurePattern", None)
        self.assertIsNotNone(scene_type)
        self.assertIsNotNone(pattern_type)
        scene = scene_type()

        static = scene.frame(0, pattern_type.STATIC)
        left = scene.frame(0, pattern_type.LEFT_BIAS)
        right = scene.frame(0, pattern_type.RIGHT_BIAS)

        self.assertEqual(static.shape, (48, 64))
        self.assertEqual(static.dtype, np.dtype("uint16"))
        self.assertLessEqual(int(static.max()), 4095)
        self.assertGreater(int(static.sum()), 0)
        self.assertGreater(int(left[:, :32].sum()), int(left[:, 32:].sum()))
        self.assertGreater(int(right[:, 32:].sum()), int(right[:, :32].sum()))

    def test_cop_sway_moves_the_raw_count_centroid_periodically(self) -> None:
        simulator = importlib.import_module("client.device.simulator")
        sway_pattern = getattr(simulator.PressurePattern, "COP_SWAY", None)
        self.assertIsNotNone(sway_pattern)
        try:
            scene = simulator.PressureScene(sway_period_frames=12, sway_columns=3.0)
        except TypeError as exc:
            self.fail(f"COP sway configuration is missing: {exc}")

        centered = scene.frame(0, sway_pattern)
        shifted = scene.frame(3, sway_pattern)
        x = np.arange(64, dtype=np.float64)
        centered_x = float((centered.sum(axis=0) * x).sum() / centered.sum())
        shifted_x = float((shifted.sum(axis=0) * x).sum() / shifted.sum())

        self.assertGreater(shifted_x - centered_x, 2.0)

    def test_transport_defaults_to_hardware_rate_and_streams_custom_frames(self) -> None:
        simulator = importlib.import_module("client.device.simulator")
        transport_type = getattr(simulator, "SyntheticP4864Transport", None)
        self.assertIsNotNone(transport_type)
        transport = transport_type(
            _profile(),
            realtime=False,
            max_frames=2,
            frame_source=lambda index: np.full(
                (48, 64), index + 10, dtype=np.uint16
            ),
        )
        parser = DaoOneP4864Parser(_profile(), allow_unverified=True)
        decoded = []
        while not transport.exhausted:
            decoded.extend(parser.feed(transport.read(700)))

        self.assertEqual(transport.baud_rate, 1_000_000)
        self.assertEqual(transport.rate_hz, 12.0)
        self.assertEqual([int(frame.values[0, 0]) for frame in decoded], [10, 11])
        self.assertEqual(transport.read(700), b"")

    def test_realtime_pacing_has_controlled_jitter_and_can_emit_sticky_frames(self) -> None:
        simulator = importlib.import_module("client.device.simulator")

        class FakeClock:
            def __init__(self) -> None:
                self.now_ns = 0
                self.delays: list[float] = []

            def monotonic_ns(self) -> int:
                return self.now_ns

            def sleep(self, seconds: float) -> None:
                self.delays.append(seconds)
                self.now_ns += round(seconds * 1_000_000_000)

        clock = FakeClock()
        transport = simulator.SyntheticP4864Transport(
            _profile(),
            realtime=True,
            rate_hz=12.0,
            jitter_fraction=0.1,
            max_frames=4,
            random_seed=8200,
            monotonic_ns=clock.monotonic_ns,
            sleep=clock.sleep,
        )

        sticky_wire = transport.read(6151 * 4)
        decoded = DaoOneP4864Parser(_profile(), allow_unverified=True).feed(
            sticky_wire
        )

        self.assertIsInstance(transport, ByteTransport)
        self.assertEqual(len(decoded), 4)
        self.assertEqual(len(clock.delays), 3)
        self.assertTrue(all(0.075 <= delay <= 0.092 for delay in clock.delays))

    def test_fault_plan_injects_wire_errors_partial_frame_noise_and_disconnect(self) -> None:
        simulator = importlib.import_module("client.device.simulator")
        fault_kind = getattr(simulator, "FaultKind", None)
        fault_plan_type = getattr(simulator, "FaultPlan", None)
        self.assertIsNotNone(fault_kind)
        self.assertIsNotNone(fault_plan_type)
        fault_plan = fault_plan_type(
            events={
                0: (fault_kind.NOISE_PREFIX,),
                1: (fault_kind.BAD_LENGTH,),
                2: (fault_kind.BAD_CHECKSUM,),
                3: (fault_kind.BAD_TAIL,),
                4: (fault_kind.TRUNCATE,),
                6: (fault_kind.DISCONNECT,),
            },
            noise_prefix=b"noise",
        )
        transport = simulator.SyntheticP4864Transport(
            _profile(),
            realtime=False,
            max_frames=10,
            fault_plan=fault_plan,
            frame_source=lambda index: np.full(
                (48, 64), index + 1, dtype=np.uint16
            ),
        )
        parser = DaoOneP4864Parser(_profile(), allow_unverified=True)
        decoded = []

        with self.assertRaises(TransportDisconnected):
            while True:
                decoded.extend(parser.feed(transport.read(10_000)))

        self.assertEqual([int(frame.values[0, 0]) for frame in decoded], [1, 6])
        self.assertGreaterEqual(parser.statistics.length_failures, 1)
        self.assertGreaterEqual(parser.statistics.checksum_failures, 1)
        self.assertGreaterEqual(parser.statistics.tail_failures, 2)
        self.assertGreaterEqual(parser.statistics.resynchronizations, 1)

    def test_capture_replay_verifies_digest_and_uses_byte_transport(self) -> None:
        simulator = importlib.import_module("client.device.simulator")
        replay_type = getattr(simulator, "CaptureReplayTransport", None)
        self.assertIsNotNone(replay_type)
        wire = b"".join(
            simulator.encode_frame(
                np.full((48, 64), marker, dtype=np.uint16), _profile()
            )
            for marker in (21, 22)
        )
        digest = hashlib.sha256(wire).hexdigest()
        parser = DaoOneP4864Parser(_profile(), allow_unverified=True)

        with tempfile.TemporaryDirectory() as directory:
            capture = Path(directory) / "capture.bin"
            capture.write_bytes(wire)
            with self.assertRaises(ValueError):
                replay_type.from_file(capture, expected_sha256="0" * 64)
            replay = replay_type.from_file(capture, expected_sha256=digest)
            decoded = []
            while not replay.exhausted:
                decoded.extend(parser.feed(replay.read(733)))

        self.assertEqual([int(frame.values[0, 0]) for frame in decoded], [21, 22])


if __name__ == "__main__":
    unittest.main()
