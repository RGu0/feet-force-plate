"""Compare immutable-frame temporal mean denoising on known-load captures.

The experiment deliberately re-fits the two voltage-to-force coefficients for
each reducer and reports only loads excluded from that fit.  It does not alter
raw captures or the serial protocol parser.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from scripts.fit_bounded_voltage_force_model import (
    PreparedLoad,
    decode_capture,
    fit_model,
    predicted_force,
    stable_mask,
)


def centered_moving_mean(frames: np.ndarray, window_frames: int) -> np.ndarray:
    """Apply an edge-padded centred time-domain mean to every sensor point."""

    if window_frames <= 0 or window_frames % 2 == 0:
        raise ValueError("window_frames must be a positive odd integer")
    if window_frames == 1:
        return frames.copy()
    half_window = window_frames // 2
    padded = np.pad(frames, ((half_window, half_window), (0, 0), (0, 0)), mode="edge")
    cumulative = np.concatenate((np.zeros_like(padded[:1]), np.cumsum(padded, axis=0)), axis=0)
    return (cumulative[window_frames:] - cumulative[:-window_frames]) / window_frames


def prepare_mean_reduced_loads(
    *, baseline_frames: np.ndarray, loads: list[tuple[str, float, np.ndarray]], window_frames: int
) -> list[PreparedLoad]:
    """Prepare loads with a temporal moving mean and stable-frame arithmetic mean."""

    raw_baseline = np.median(baseline_frames, axis=0)
    baseline_mad = np.median(np.abs(baseline_frames - raw_baseline), axis=0)
    threshold = np.maximum(1.0, 3.0 * baseline_mad)
    baseline = np.mean(centered_moving_mean(baseline_frames, window_frames), axis=0)
    smoothed_loads = [
        (label, mass_g, centered_moving_mean(frames, window_frames))
        for label, mass_g, frames in loads
    ]
    union_active = np.any(
        np.stack([np.maximum(np.mean(frames, axis=0) - baseline, 0.0) > threshold for _, _, frames in smoothed_loads]),
        axis=0,
    )
    if not union_active.any():
        raise ValueError("no responsive sensor points across supplied captures")

    prepared: list[PreparedLoad] = []
    for label, mass_g, frames in smoothed_loads:
        aggregate = np.sum(np.maximum(frames - baseline, 0.0)[:, union_active], axis=1)
        stable, _, _ = stable_mask(aggregate)
        delta = np.maximum(np.mean(frames[stable], axis=0) - baseline, 0.0)
        prepared.append(
            PreparedLoad(
                label=label,
                mass_g=mass_g,
                target_force_n=mass_g / 1000.0 * 9.80665,
                delta_count=delta,
                active=delta > threshold,
                stable_frame_count=int(stable.sum()),
            )
        )
    return prepared


def parse_load(value: str) -> tuple[str, float, Path]:
    label, mass_g, path = value.split(":", maxsplit=2)
    return label, float(mass_g), Path(path)


def evaluate(
    *, baseline: Path, loads: list[tuple[str, float, Path]], training_labels: set[str], windows: list[int]
) -> dict[str, object]:
    baseline_frames = decode_capture(baseline)
    decoded_loads = [(label, mass_g, decode_capture(path)) for label, mass_g, path in loads]
    variants: list[dict[str, object]] = []
    for window in windows:
        prepared = prepare_mean_reduced_loads(
            baseline_frames=baseline_frames, loads=decoded_loads, window_frames=window
        )
        training = [load for load in prepared if load.label in training_labels]
        alpha, beta = fit_model(training)
        held_out = []
        for load in prepared:
            if load.label in training_labels:
                continue
            predicted_n = predicted_force(load, alpha=alpha, beta=beta)
            error_percent = (predicted_n - load.target_force_n) / load.target_force_n * 100.0
            held_out.append(
                {
                    "label": load.label,
                    "target_mass_kg": load.mass_g / 1000.0,
                    "inferred_mass_kg": predicted_n / 9.80665,
                    "error_percent": error_percent,
                }
            )
        variants.append(
            {
                "reducer": "mean" if window == 1 else f"{window}-frame-centred-moving-mean + mean",
                "window_frames": window,
                "candidate_parameters": {"alpha": alpha, "beta": beta},
                "held_out_loads": held_out,
                "held_out_mean_absolute_error_percent": float(
                    np.mean([abs(record["error_percent"]) for record in held_out])
                ),
            }
        )
    return {
        "method": "per-cell time-domain mean denoising; raw frames unchanged; coefficients re-fit per variant",
        "training_labels": sorted(training_labels),
        "variants": variants,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--load", action="append", type=parse_load, required=True)
    parser.add_argument("--training-label", action="append", required=True)
    parser.add_argument("--window", type=int, action="append", required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            evaluate(
                baseline=args.baseline,
                loads=args.load,
                training_labels=set(args.training_label),
                windows=args.window,
            ),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
