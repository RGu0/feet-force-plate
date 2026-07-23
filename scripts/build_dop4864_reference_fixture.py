"""Build a de-identified four-pose DO-P4864 replay fixture from local captures.

Input capture bytes must stay outside the repository.  This command decodes
them through the observed compact parser, drops capture timestamps and absolute
amplitudes, and writes only per-pose relative uint8 matrices plus aggregate
metadata for deterministic UI/algorithm tests.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from client.device.protocol import DaoOneP4864Parser, ProtocolProfile


POSES = (
    "open_eyes_bilateral",
    "closed_eyes_bilateral",
    "tandem_left_front",
    "tandem_right_front",
)
SCHEMA_VERSION = "do-p4864-reference-protocol/1"


def _profile() -> ProtocolProfile:
    return ProtocolProfile.observed_compact_8bit(
        version="do-p4864/observed-compact-column-major-48x64-20260721"
    )


def _relative_fixture(capture: Path) -> np.ndarray:
    parser = DaoOneP4864Parser(_profile(), allow_unverified=True)
    frames = parser.feed(capture.read_bytes())
    if len(frames) < 20:
        raise ValueError(f"{capture} does not contain enough valid frames")
    values = np.stack([frame.values for frame in frames]).astype(np.float64)
    nonzero = values[values > 0]
    if not len(nonzero):
        raise ValueError(f"{capture} contains no contact values")
    scale = float(np.percentile(nonzero, 99))
    if scale <= 0:
        raise ValueError(f"{capture} has no positive relative scale")
    # Do not retain timestamps, source indexes, checksums, raw byte values, or
    # absolute load magnitude.  The fixture keeps only spatial/temporal shape.
    return np.rint(np.clip(values / scale, 0.0, 1.0) * 255.0).astype(np.uint8)


def build(*, inputs: dict[str, Path], output: Path, metadata: Path) -> dict[str, object]:
    if set(inputs) != set(POSES):
        raise ValueError("inputs must contain every declared reference pose")
    matrices = {pose: _relative_fixture(inputs[pose]) for pose in POSES}
    output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        output,
        schema_version=np.asarray(SCHEMA_VERSION),
        nominal_frame_interval_ms=np.asarray(50, dtype=np.int32),
        **matrices,
    )
    result = {
        "schema_version": SCHEMA_VERSION,
        "fixture_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "nominal_frame_interval_ms": 50,
        "poses": {
            pose: {"frames": int(matrices[pose].shape[0]), "shape": [48, 64]}
            for pose in POSES
        },
        "deidentification": {
            "retained": "per-pose relative 48x64 matrix sequence only",
            "removed": [
                "serial bytes",
                "capture timestamps",
                "source indexes",
                "absolute amplitude",
                "operator and device identifiers",
            ],
        },
        "usage": "Use as the first input for UI and algorithm replay tests before reconnecting a physical device.",
        "boundary": "Reference engineering fixture; not a clinical dataset, calibrated pressure record, or customer report input.",
    }
    metadata.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    arguments = argparse.ArgumentParser(description=__doc__)
    for pose in POSES:
        arguments.add_argument(f"--{pose.replace('_', '-')}", type=Path, required=True)
    arguments.add_argument("--output", type=Path, required=True)
    arguments.add_argument("--metadata", type=Path, required=True)
    options = arguments.parse_args()
    inputs = {
        pose: getattr(options, pose)
        for pose in POSES
    }
    print(json.dumps(build(inputs=inputs, output=options.output, metadata=options.metadata), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
