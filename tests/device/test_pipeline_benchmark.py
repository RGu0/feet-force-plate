import unittest

from client.device.pipeline_benchmark import run_pipeline_benchmark


class PipelineBenchmarkTests(unittest.TestCase):
    def test_slow_storage_ui_stall_and_parallel_reader_preserve_storage_frames(self) -> None:
        result = run_pipeline_benchmark(
            frame_count=36,
            storage_capacity=3,
            storage_delay_seconds=0.0005,
        )

        self.assertEqual(result["storage_frames_submitted"], 36)
        self.assertEqual(result["storage_frames_consumed"], 36)
        self.assertEqual(result["storage_silent_drops"], 0)
        self.assertGreater(result["storage_producer_waits"], 0)
        self.assertEqual(result["display_latest_source_index"], 35)
        self.assertEqual(result["display_replacements"], 35)
        self.assertGreater(result["parallel_upload_reader_iterations"], 0)
        self.assertEqual(result["matrix_shape"], [48, 64])
        self.assertEqual(result["input_nominal_hz"], 20.7)


if __name__ == "__main__":
    unittest.main()
