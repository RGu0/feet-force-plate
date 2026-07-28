import unittest

from cloud.analysis.features import FeaturePipeline
from cloud.analysis.models import CalibrationLevel, RawSession, SessionContext


def make_frame(left_value: int = 1, right_value: int = 3) -> tuple[int, ...]:
    values: list[int] = []
    for _row in range(48):
        values.extend([left_value] * 32)
        values.extend([right_value] * 32)
    return tuple(values)


def make_context(**overrides: object) -> SessionContext:
    values: dict[str, object] = {
        "tenant_id": "tenant-a",
        "session_id": "session-a",
        "manifest_sha256": "a" * 64,
        "device_model": "DO-P4864",
        "actual_sample_rate_hz": 12.0,
        "calibration_level": CalibrationLevel.RELATIVE,
        "calibration_version": "calibration/1",
        "duration_seconds": 20.0,
        "validity_status": "VALID",
        "manifest_status": "VERIFIED",
        "cloud_quality_status": "PASS",
        "quality_flags": frozenset(),
        "test_protocol_id": "standard-screening",
        "profile_fields": frozenset(),
    }
    values.update(overrides)
    return SessionContext(**values)


class FeaturePipelineTests(unittest.TestCase):
    def test_extracts_deterministic_first_level_features_from_48_by_64_frames(self) -> None:
        raw = RawSession(context=make_context(), frames=(make_frame(), make_frame()))
        pipeline = FeaturePipeline("features/1")

        first = pipeline.extract(raw, {"contact_threshold": 0})
        second = pipeline.extract(raw, {"contact_threshold": 0})

        self.assertEqual(first, second)
        self.assertEqual(first.pipeline_version, "features/1")
        self.assertEqual(first.total_load_by_frame, (6144.0, 6144.0))
        self.assertEqual(first.left_load_by_frame, (1536.0, 1536.0))
        self.assertEqual(first.right_load_by_frame, (4608.0, 4608.0))
        self.assertEqual(first.anterior_load_by_frame, (3072.0, 3072.0))
        self.assertEqual(first.posterior_load_by_frame, (3072.0, 3072.0))
        self.assertEqual(first.contact_area_by_frame, (3072, 3072))
        self.assertEqual(len(first.cop_xy_by_frame), 2)
        self.assertAlmostEqual(first.cop_xy_by_frame[0][0], 39.5)
        self.assertAlmostEqual(first.cop_xy_by_frame[0][1], 23.5)
        self.assertEqual(first.actual_sample_rate_hz, 12.0)
        self.assertEqual(len(first.mean_sensor_load), 48 * 64)
        self.assertEqual(first.mean_sensor_load[:32], tuple([1.0] * 32))
        self.assertEqual(first.mean_sensor_load[32:64], tuple([3.0] * 32))

    def test_cache_key_covers_manifest_pipeline_calibration_and_parameters(self) -> None:
        raw = RawSession(context=make_context(), frames=(make_frame(),))

        baseline = FeaturePipeline("features/1").extract(raw, {"contact_threshold": 0})
        manifest_changed = FeaturePipeline("features/1").extract(
            RawSession(context=make_context(manifest_sha256="b" * 64), frames=raw.frames),
            {"contact_threshold": 0},
        )
        calibration_changed = FeaturePipeline("features/1").extract(
            RawSession(
                context=make_context(calibration_version="calibration/2"),
                frames=raw.frames,
            ),
            {"contact_threshold": 0},
        )
        pipeline_changed = FeaturePipeline("features/2").extract(
            raw, {"contact_threshold": 0}
        )
        parameters_changed = FeaturePipeline("features/1").extract(
            raw, {"contact_threshold": 2}
        )

        keys = {
            baseline.cache_key,
            manifest_changed.cache_key,
            calibration_changed.cache_key,
            pipeline_changed.cache_key,
            parameters_changed.cache_key,
        }
        self.assertEqual(len(keys), 5)

    def test_rejects_frames_that_do_not_match_the_approved_sensor_shape(self) -> None:
        raw = RawSession(context=make_context(), frames=((1, 2, 3),))

        with self.assertRaisesRegex(ValueError, "48x64"):
            FeaturePipeline("features/1").extract(raw, {})


if __name__ == "__main__":
    unittest.main()
