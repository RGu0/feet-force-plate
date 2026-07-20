import json
from queue import Full
import unittest

import numpy as np

from client.device.acquisition import LatestFrameMailbox
from client.device.pipeline import (
    RAW_COUNT_UNIT,
    DisplayCadence,
    PreallocatedFrameBuffer,
    ProcessingProfile,
    SessionVersionManifest,
    UnverifiedCalibrationError,
    VersionedDisplayProcessor,
)
from client.device.protocol import RawFrame


def _frame(index: int, value: int | None = None) -> RawFrame:
    values = np.full((48, 64), index if value is None else value, dtype=np.uint16)
    values.setflags(write=False)
    return RawFrame(
        values=values,
        host_monotonic_ns=1_000_000_000 + index * 83_333_333,
        host_wall_time_ns=2_000_000_000 + index * 83_333_333,
        source_index=index,
        device_frame_seq=None,
        device_timestamp_ns=None,
        quality_flags=frozenset(),
    )


class PreallocatedFrameBufferTests(unittest.TestCase):
    def test_fixed_capacity_fifo_never_silently_drops_storage_frames(self) -> None:
        buffer = PreallocatedFrameBuffer(capacity=2)
        buffer.append("session-pipeline", _frame(0))
        buffer.append("session-pipeline", _frame(1))

        with self.assertRaises(Full):
            buffer.append("session-pipeline", _frame(2), timeout=0.0)

        first = buffer.get_nowait()
        buffer.append("session-pipeline", _frame(2), timeout=0.0)
        remaining = [buffer.get_nowait(), buffer.get_nowait()]
        self.assertEqual(
            [first.frame.source_index, *(item.frame.source_index for item in remaining)],
            [0, 1, 2],
        )
        self.assertEqual(buffer.metrics.accepted_frames, 3)
        self.assertEqual(buffer.metrics.rejected_frames, 1)
        self.assertEqual(buffer.metrics.silently_dropped_frames, 0)
        self.assertEqual(buffer.allocated_slots, 2)

    def test_latest_mailbox_overwrites_display_only_frames_with_audit_count(self) -> None:
        mailbox = LatestFrameMailbox()

        for index in range(5):
            mailbox.publish(_frame(index))

        self.assertEqual(mailbox.read().source_index, 4)
        self.assertEqual(mailbox.publish_count, 5)
        self.assertEqual(mailbox.replacement_count, 4)


class RawCountAndVersionTests(unittest.TestCase):
    def test_unverified_calibration_cannot_request_physical_units(self) -> None:
        with self.assertRaises(UnverifiedCalibrationError):
            ProcessingProfile(
                algorithm_version="raw-view/1",
                filter_version="none/1",
                bad_point_version="none/1",
                interpolation_version="none/1",
                calibration_version=None,
                output_unit="kPa",
            )

    def test_display_projection_is_separate_and_does_not_overwrite_raw_counts(self) -> None:
        raw = _frame(7, value=0x0ABC)
        profile = ProcessingProfile.raw_counts_only(
            algorithm_version="raw-view/1",
            filter_version="none/1",
            bad_point_version="none/1",
            interpolation_version="none/1",
        )
        display = VersionedDisplayProcessor(profile).project(raw)

        self.assertIs(display.raw_frame, raw)
        self.assertEqual(display.unit, RAW_COUNT_UNIT)
        self.assertFalse(display.values.flags.writeable)
        self.assertIsNot(display.values, raw.values)
        np.testing.assert_array_equal(display.values, raw.values)
        np.testing.assert_array_equal(raw.values, 0x0ABC)
        self.assertEqual(display.processing_profile, profile)

    def test_parameter_content_changes_processing_identity_without_touching_raw(self) -> None:
        raw = _frame(3)
        first = ProcessingProfile.raw_counts_only(
            algorithm_version="raw-view/1",
            filter_version="median/1",
            bad_point_version="map/1",
            interpolation_version="nearest/1",
            filter_parameters=(("window", 3.0),),
            bad_points=((4, 5),),
            interpolation_parameters=(("radius", 1.0),),
        )
        second = ProcessingProfile.raw_counts_only(
            algorithm_version="raw-view/1",
            filter_version="median/1",
            bad_point_version="map/1",
            interpolation_version="nearest/1",
            filter_parameters=(("window", 5.0),),
            bad_points=((4, 5),),
            interpolation_parameters=(("radius", 1.0),),
        )

        self.assertNotEqual(first.identity_sha256, second.identity_sha256)
        VersionedDisplayProcessor(first).project(raw)
        np.testing.assert_array_equal(raw.values, 3)

    def test_session_manifest_round_trip_persists_every_required_version(self) -> None:
        manifest = SessionVersionManifest(
            data_schema_version="raw-frame/1",
            device_model="DO-P4864",
            protocol_version="do-p4864/capture-pending",
            calibration_version="UNAVAILABLE",
            algorithm_version="raw-view/1",
            filter_version="none/1",
            bad_point_version="none/1",
            interpolation_version="none/1",
            test_protocol_version="standard-screening/1",
            acquisition_mode="SCREENING",
        )

        encoded = manifest.to_json_bytes()
        restored = SessionVersionManifest.from_json_bytes(encoded)

        self.assertEqual(restored, manifest)
        self.assertEqual(json.loads(encoded)["calibration_version"], "UNAVAILABLE")
        self.assertEqual(json.loads(encoded)["acquisition_mode"], "SCREENING")


class DisplayCadenceTests(unittest.TestCase):
    def test_ui_refresh_clock_is_explicitly_independent_from_sample_clock(self) -> None:
        mailbox = LatestFrameMailbox()
        cadence = DisplayCadence(
            mailbox,
            input_nominal_hz=12.0,
            refresh_hz=30.0,
            start_monotonic_ns=0,
        )
        mailbox.publish(_frame(0))

        first = cadence.poll(now_monotonic_ns=0)
        too_soon = cadence.poll(now_monotonic_ns=20_000_000)
        same_source = cadence.poll(now_monotonic_ns=34_000_000)
        mailbox.publish(_frame(1))
        next_source = cadence.poll(now_monotonic_ns=68_000_000)

        self.assertEqual(cadence.input_nominal_hz, 12.0)
        self.assertEqual(cadence.refresh_hz, 30.0)
        self.assertEqual(first.frame.source_index, 0)
        self.assertTrue(first.is_new_source)
        self.assertIsNone(too_soon)
        self.assertEqual(same_source.frame.source_index, 0)
        self.assertFalse(same_source.is_new_source)
        self.assertEqual(next_source.frame.source_index, 1)
        self.assertTrue(next_source.is_new_source)


if __name__ == "__main__":
    unittest.main()
