"""Fit the provisional voltage-to-force model against local known-load captures."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import sys

import numpy as np
from scipy.optimize import least_squares

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.analyze_force_calibration_capture import (
    GRAVITY_M_S2,
    SENSOR_AREA_MM2,
    decode_capture,
    stable_mask,
)
from client.hardware_standardization.spatial_integration import integrate_regular_grid_force


ADC_REFERENCE_V = 4.096
ADC_MAX_CODE = 255.0
R0 = 2.2
ROWS = 48
COLUMNS = 64
PITCH_X_MM = 7.99
PITCH_Y_MM = 7.99


@dataclass(frozen=True, slots=True)
class PreparedLoad:
    label: str
    mass_g: float
    target_force_n: float
    delta_count: np.ndarray
    active: np.ndarray
    stable_frame_count: int


def prepare_loads(
    *, baseline_frames: np.ndarray, loads: list[tuple[str, float, np.ndarray]]
) -> list[PreparedLoad]:
    baseline = np.median(baseline_frames, axis=0)
    baseline_mad = np.median(np.abs(baseline_frames - baseline), axis=0)
    threshold = np.maximum(1.0, 3.0 * baseline_mad)
    median_deltas = [np.maximum(np.median(frames, axis=0) - baseline, 0.0) for _, _, frames in loads]
    union_active = np.any(np.stack([delta > threshold for delta in median_deltas]), axis=0)
    if not union_active.any():
        raise ValueError("no responsive sensor points across supplied captures")

    prepared: list[PreparedLoad] = []
    for label, mass_g, frames in loads:
        aggregate = np.sum(np.maximum(frames - baseline, 0.0)[:, union_active], axis=1)
        stable, _, _ = stable_mask(aggregate)
        delta = np.maximum(np.median(frames[stable], axis=0) - baseline, 0.0)
        prepared.append(
            PreparedLoad(
                label=label,
                mass_g=mass_g,
                target_force_n=mass_g / 1000.0 * GRAVITY_M_S2,
                delta_count=delta,
                active=delta > threshold,
                stable_frame_count=int(stable.sum()),
            )
        )
    return prepared


def predicted_force(load: PreparedLoad, *, alpha: float, beta: float) -> float:
    voltage = load.delta_count * ADC_REFERENCE_V / ADC_MAX_CODE
    force = np.zeros_like(voltage)
    valid = load.active & (voltage > 0.0) & (voltage < ADC_REFERENCE_V)
    force[valid] = (
        (10.0**beta * voltage[valid] / R0 / (ADC_REFERENCE_V - voltage[valid]))
        ** (1.0 / alpha)
        / 1000.0
    )
    integration = integrate_regular_grid_force(
        force_n=tuple(float(value) for value in force.reshape(-1, order="F")),
        active=tuple(bool(value) for value in load.active.reshape(-1, order="F")),
        rows=ROWS,
        columns=COLUMNS,
        pitch_x_mm=PITCH_X_MM,
        pitch_y_mm=PITCH_Y_MM,
        sensor_area_mm2=SENSOR_AREA_MM2,
    )
    return integration.integrated_force_n


def fit_model(training: list[PreparedLoad]) -> tuple[float, float]:
    def residual(parameters: np.ndarray) -> np.ndarray:
        alpha = float(np.exp(parameters[0]))
        beta = float(parameters[1])
        return np.asarray(
            [
                (predicted_force(load, alpha=alpha, beta=beta) - load.target_force_n)
                / load.target_force_n
                for load in training
            ]
        )

    result = least_squares(
        residual,
        x0=np.asarray([np.log(0.751), 2.657]),
        bounds=(np.asarray([np.log(0.1), -5.0]), np.asarray([np.log(5.0), 20.0])),
    )
    if not result.success:
        raise RuntimeError(f"force-model fitting failed: {result.message}")
    return float(np.exp(result.x[0])), float(result.x[1])


def load_argument(value: str) -> tuple[str, float, Path]:
    label, mass_g, path = value.split(":", maxsplit=2)
    return label, float(mass_g), Path(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--load", action="append", type=load_argument, required=True)
    parser.add_argument("--training-label", action="append", required=True)
    args = parser.parse_args()
    prepared = prepare_loads(
        baseline_frames=decode_capture(args.baseline),
        loads=[(label, mass_g, decode_capture(path)) for label, mass_g, path in args.load],
    )
    training_labels = set(args.training_label)
    training = [load for load in prepared if load.label in training_labels]
    if len(training) < 3:
        raise ValueError("at least three training load levels are required")
    alpha, beta = fit_model(training)
    records = []
    for load in prepared:
        predicted = predicted_force(load, alpha=alpha, beta=beta)
        records.append(
            {
                "label": load.label,
                "mass_g": load.mass_g,
                "training": load.label in training_labels,
                "stable_frame_count": load.stable_frame_count,
                "active_sensor_count": int(load.active.sum()),
                "target_force_n": load.target_force_n,
                "predicted_force_n": predicted,
                "inferred_mass_kg": predicted / GRAVITY_M_S2,
                "error_percent": (predicted - load.target_force_n) / load.target_force_n * 100.0,
            }
        )
    print(
        json.dumps(
            {
                "method": {
                    "fit_parameters": ["alpha", "beta"],
                    "fixed_parameters": {"v0_v": ADC_REFERENCE_V, "r0": R0},
                    "spatial_method": "per-point force -> divide by 6mm-circle area -> bilinear pressure interpolation -> area integration",
                },
                "candidate_parameters": {"alpha": alpha, "beta": beta},
                "loads": records,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
