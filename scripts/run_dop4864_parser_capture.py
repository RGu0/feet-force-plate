"""Capture an observed DO-P4864 stream through the current parser.

Raw bytes are intentionally written only beneath a caller-selected local output
directory (normally ignored ``tmp/hardware``).  The JSON summary is safe to use
as issue evidence because it contains only aggregate counters and a SHA-256.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time

import numpy as np

# Permit ``uv run python scripts/run_dop4864_parser_capture.py`` from the
# repository root without requiring a caller-supplied PYTHONPATH.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from client.device.protocol import DaoOneP4864Parser, ProtocolProfile
from client.device.serial_transport import SerialByteTransport
from client.device.transport import TransportDisconnected
from client.hardware_standardization.do_p4864 import DoP4864StandardizationAdapter


def _quantiles_ms(values_ns: list[int]) -> dict[str, float | None]:
    if not values_ns:
        return {"p50": None, "p95": None, "p99": None, "maximum": None}
    values_ms = np.asarray(values_ns, dtype=np.float64) / 1_000_000.0
    return {
        "p50": float(np.quantile(values_ms, 0.50)),
        "p95": float(np.quantile(values_ms, 0.95)),
        "p99": float(np.quantile(values_ms, 0.99)),
        "maximum": float(values_ms.max()),
    }


def _capture(*, device: str, seconds: float, output_dir: Path, read_size: int) -> dict[str, object]:
    if seconds <= 0:
        raise ValueError("seconds must be positive")
    if read_size <= 0:
        raise ValueError("read_size must be positive")

    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    raw_path = output_dir / f"dop4864-parser-capture-{stamp}.bin"
    summary_path = output_dir / f"dop4864-parser-capture-{stamp}.json"
    profile = ProtocolProfile.observed_compact_8bit(
        version="do-p4864/observed-compact-column-major-48x64-20260721"
    )
    parser = DaoOneP4864Parser(profile)
    specification = DoP4864StandardizationAdapter.observed_compact_8bit().specification
    intervals_ns: list[int] = []
    quality_counts: dict[str, int] = {}
    previous_frame_ns: int | None = None
    started_ns = time.monotonic_ns()
    deadline_ns = started_ns + round(seconds * 1_000_000_000)
    received_bytes = 0
    disconnected: str | None = None

    transport = SerialByteTransport.open(
        device,
        timeout_seconds=0.25,
        baud_rate=specification.serial_baud_rate,
        data_bits=specification.serial_data_bits,
        parity=specification.serial_parity,
        stop_bits=specification.serial_stop_bits,
    )
    try:
        with raw_path.open("xb") as raw_file:
            while time.monotonic_ns() < deadline_ns:
                try:
                    chunk = transport.read(read_size)
                except TransportDisconnected as exc:
                    disconnected = str(exc)
                    break
                if not chunk:
                    continue
                raw_file.write(chunk)
                received_bytes += len(chunk)
                for frame in parser.feed(chunk):
                    if previous_frame_ns is not None:
                        intervals_ns.append(frame.host_monotonic_ns - previous_frame_ns)
                    previous_frame_ns = frame.host_monotonic_ns
                    for flag in frame.quality_flags:
                        quality_counts[flag] = quality_counts.get(flag, 0) + 1
            raw_file.flush()
            os.fsync(raw_file.fileno())
    finally:
        transport.close()

    ended_ns = time.monotonic_ns()
    raw_digest = hashlib.sha256(raw_path.read_bytes()).hexdigest()
    stats = parser.statistics
    result: dict[str, object] = {
        "tool": "scripts/run_dop4864_parser_capture.py",
        "captured_at_utc": stamp,
        "device": device,
        "serial": {
            "baud_rate": specification.serial_baud_rate,
            "format": f"{specification.serial_data_bits}{specification.serial_parity}{specification.serial_stop_bits}",
        },
        "requested_duration_seconds": seconds,
        "elapsed_duration_seconds": (ended_ns - started_ns) / 1_000_000_000,
        "raw_capture": {
            "local_path": str(raw_path),
            "sha256": raw_digest,
            "bytes": received_bytes,
        },
        "profile": {
            "version": profile.version,
            "frame_length": profile.frame_length,
            "payload_mapping": "uint8(frame[5:3077]).reshape((48, 64), order='F')",
            "checksum_policy": profile.checksum_policy.value,
            "enforce_wire_length": profile.enforce_wire_length,
        },
        "parser": {
            "decoded_frames": stats.valid_frames,
            "invalid_frames": stats.invalid_frames,
            "resynchronizations": stats.resynchronizations,
            "discarded_bytes": stats.discarded_bytes,
            "peak_buffer_bytes": stats.peak_buffer_bytes,
            "buffered_bytes_at_end": parser.buffered_bytes,
            "checksum_observations": stats.checksum_observations,
            "checksum_mismatches": stats.checksum_mismatches,
            "quality_flag_counts": quality_counts,
            "host_frame_intervals_ms": _quantiles_ms(intervals_ns),
        },
        "outcome": "DISCONNECTED" if disconnected else "COMPLETED",
        "disconnect_reason": disconnected,
        "boundary": "Actual captures establish the compact frame boundary, big-endian length, header, function byte, tail, and column-major mapping. CheckSum remains audit-only; raw-value semantics remain independently unvalidated. Raw bytes are local-only and must not be committed.",
    }
    summary_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", required=True, help="serial device, e.g. /dev/cu.usbserial-130")
    parser.add_argument("--seconds", type=float, default=600.0)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--read-size", type=int, default=16_384)
    args = parser.parse_args()
    print(json.dumps(_capture(**vars(args)), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
