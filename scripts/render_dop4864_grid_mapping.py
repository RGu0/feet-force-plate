"""Render and summarize a 3×3 compact-payload spatial mapping check.

Input captures are local-only files, normally below ignored ``tmp/hardware``.
The generated heatmap is diagnostic evidence for coordinate order; it is not a
calibrated pressure image.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import PowerNorm

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from client.device.protocol import DaoOneP4864Parser, ProtocolProfile


LABELS = (
    ("upper-left", "Physical upper-left"),
    ("upper-center", "Physical upper-center"),
    ("upper-right", "Physical upper-right"),
    ("middle-left", "Physical middle-left"),
    ("center", "Physical center"),
    ("middle-right", "Physical middle-right"),
    ("lower-left", "Physical lower-left"),
    ("lower-center", "Physical lower-center"),
    ("lower-right", "Physical lower-right"),
)


def mean_capture(directory: Path) -> tuple[np.ndarray, int, Path]:
    """Return the current-parser mean matrix for one local raw capture."""

    files = sorted(directory.glob("*.bin"))
    if len(files) != 1:
        raise RuntimeError(f"expected exactly one raw capture in {directory}, found {len(files)}")
    parser = DaoOneP4864Parser(
        ProtocolProfile.observed_compact_8bit(
            version="do-p4864/observed-compact-column-major-48x64-20260721"
        ),
    )
    frames = parser.feed(files[0].read_bytes())
    if not frames:
        raise RuntimeError(f"no frames decoded from {files[0]}")
    return np.stack([frame.values for frame in frames]).mean(axis=0), len(frames), files[0]


def centroid(matrix: np.ndarray) -> tuple[float | None, float | None]:
    """Return the positive baseline-difference centroid as (row, column)."""

    total = float(matrix.sum())
    if total <= 0:
        return None, None
    rows, columns = np.indices(matrix.shape)
    return float((rows * matrix).sum() / total), float((columns * matrix).sum() / total)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args()

    before, before_frames, before_path = mean_capture(args.root / "baseline")
    after, after_frames, after_path = mean_capture(args.root / "baseline-after")
    baseline = (before + after) / 2.0
    results = []
    for directory_name, label in LABELS:
        mean, count, raw_path = mean_capture(args.root / directory_name)
        delta = np.maximum(mean - baseline, 0)
        row, column = centroid(delta)
        results.append(
            {
                "directory": directory_name,
                "label": label,
                "frames": count,
                "raw_path": str(raw_path),
                "delta": delta,
                "row": row,
                "column": column,
                "max": float(delta.max()),
            }
        )

    ceiling = max(item["max"] for item in results)
    figure, axes = plt.subplots(3, 3, figsize=(13, 10), constrained_layout=True)
    norm = PowerNorm(gamma=0.45, vmin=0, vmax=max(1e-6, ceiling))
    image = None
    for axis, item in zip(axes.flat, results):
        image = axis.imshow(
            item["delta"], cmap="inferno", interpolation="nearest", origin="upper", norm=norm, aspect="auto"
        )
        axis.plot(item["column"], item["row"], "x", color="#00E5FF", markersize=9, markeredgewidth=2)
        axis.set_title(f"{item['label']}\ncenter ({item['row']:.1f}, {item['column']:.1f})", fontsize=10, fontweight="bold")
        axis.set_xticks([0, 32, 63])
        axis.set_yticks([0, 24, 47])
        axis.set_xlabel("column", fontsize=8)
        axis.set_ylabel("row", fontsize=8)
    assert image is not None
    colorbar = figure.colorbar(image, ax=axes.ravel().tolist(), shrink=0.7)
    colorbar.set_label("Positive mean raw-byte change vs mean empty-board baseline")
    figure.suptitle(
        "DO-P4864 3×3 physical mapping — column-major 48 rows × 64 columns\n"
        "Candidate raw-byte response only; not calibrated pressure",
        fontsize=15,
        fontweight="bold",
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(args.output, dpi=180, bbox_inches="tight")
    plt.close(figure)

    summary = {
        "interpretation": "uint8(frame[5:3077]).reshape((48, 64), order='F')",
        "baseline": {
            "before_frames": before_frames,
            "after_frames": after_frames,
            "raw_paths": [str(before_path), str(after_path)],
            "method": "mean(before, after) / 2",
            "mean_absolute_byte_drift": float(np.abs(after - before).mean()),
            "maximum_absolute_byte_drift": float(np.abs(after - before).max()),
        },
        "results": [
            {key: value for key, value in item.items() if key not in {"delta", "raw_path"}}
            for item in results
        ],
        "boundary": "Fixed-object 3×3 coordinate check; not calibration, pressure units, or CheckSum verification.",
    }
    args.summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
