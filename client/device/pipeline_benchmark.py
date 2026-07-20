"""Repeatable short stress benchmark for the owned raw-frame pipeline."""

from __future__ import annotations

import argparse
import hashlib
import json
import threading
import time
from typing import Any

import numpy as np

from .acquisition import LatestFrameMailbox
from .pipeline import PreallocatedFrameBuffer
from .protocol import RawFrame


def _frame(index: int) -> RawFrame:
    values = np.full((48, 64), index & 0x0FFF, dtype=np.uint16)
    values.setflags(write=False)
    return RawFrame(
        values=values,
        host_monotonic_ns=index * 83_333_333,
        host_wall_time_ns=index * 83_333_333,
        source_index=index,
        device_frame_seq=None,
        device_timestamp_ns=None,
        quality_flags=frozenset({"BENCHMARK_SYNTHETIC"}),
    )


def run_pipeline_benchmark(
    *,
    frame_count: int = 120,
    storage_capacity: int = 4,
    storage_delay_seconds: float = 0.001,
) -> dict[str, Any]:
    """Stress slow storage, a stalled display, and a parallel read workload."""

    if frame_count <= 0 or storage_capacity <= 0:
        raise ValueError("frame_count and storage_capacity must be positive")
    if storage_delay_seconds < 0:
        raise ValueError("storage_delay_seconds cannot be negative")
    storage = PreallocatedFrameBuffer(capacity=storage_capacity)
    display = LatestFrameMailbox()
    consumed: list[int] = []
    parallel_upload_reader_iterations = 0
    stop_parallel = threading.Event()
    parallel_started = threading.Event()

    def storage_consumer() -> None:
        for _ in range(frame_count):
            item = storage.get(timeout=5.0)
            time.sleep(storage_delay_seconds)
            consumed.append(item.frame.source_index)

    def parallel_upload_reader() -> None:
        nonlocal parallel_upload_reader_iterations
        while not stop_parallel.is_set():
            frame = display.read()
            payload = b"" if frame is None else frame.values.tobytes(order="C")
            hashlib.sha256(payload).digest()
            parallel_upload_reader_iterations += 1
            parallel_started.set()
            time.sleep(0)

    consumer = threading.Thread(target=storage_consumer, name="benchmark-slow-storage")
    reader = threading.Thread(
        target=parallel_upload_reader,
        name="benchmark-parallel-upload-reader",
    )
    started_ns = time.perf_counter_ns()
    consumer.start()
    reader.start()
    if not parallel_started.wait(1.0):
        raise TimeoutError("parallel reader did not start")
    for index in range(frame_count):
        frame = _frame(index)
        storage.append("benchmark-session", frame)
        display.publish(frame)
    consumer.join(timeout=10.0)
    stop_parallel.set()
    reader.join(timeout=2.0)
    elapsed_ns = time.perf_counter_ns() - started_ns
    if consumer.is_alive() or reader.is_alive():
        raise TimeoutError("pipeline benchmark worker did not finish")
    metrics = storage.metrics
    return {
        "benchmark_schema": "ray-83-pipeline-benchmark/1",
        "input_nominal_hz": 12.0,
        "matrix_shape": [48, 64],
        "frame_count": frame_count,
        "storage_capacity": storage_capacity,
        "storage_delay_seconds": storage_delay_seconds,
        "storage_frames_submitted": metrics.accepted_frames,
        "storage_frames_consumed": len(consumed),
        "storage_order_preserved": consumed == list(range(frame_count)),
        "storage_silent_drops": metrics.silently_dropped_frames,
        "storage_producer_waits": metrics.producer_waits,
        "storage_peak_depth": metrics.peak_depth,
        "display_latest_source_index": (
            None if display.read() is None else display.read().source_index
        ),
        "display_replacements": display.replacement_count,
        "parallel_upload_reader_iterations": parallel_upload_reader_iterations,
        "elapsed_seconds": elapsed_ns / 1_000_000_000,
        "evidence_boundary": "synthetic automatic benchmark; not physical disk, USB, or UI",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frames", type=int, default=120)
    parser.add_argument("--capacity", type=int, default=4)
    parser.add_argument("--storage-delay", type=float, default=0.001)
    args = parser.parse_args()
    print(
        json.dumps(
            run_pipeline_benchmark(
                frame_count=args.frames,
                storage_capacity=args.capacity,
                storage_delay_seconds=args.storage_delay,
            ),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
