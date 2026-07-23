"""Leave-one-load-out comparison of provisional DP-P4864 calibration variants.

The response-chart screenshot is used only as a qualitative monotonicity and
possible-saturation constraint. It is not treated as numerical resistance data.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from math import exp, log
from pathlib import Path

import numpy as np
from scipy.optimize import least_squares

from scripts.fit_bounded_voltage_force_model import (
    ADC_MAX_CODE,
    ADC_REFERENCE_V,
    COLUMNS,
    PITCH_X_MM,
    PITCH_Y_MM,
    ROWS,
    PreparedLoad,
    SENSOR_AREA_MM2,
    decode_capture,
    stable_mask,
)
from client.hardware_standardization.spatial_integration import integrate_regular_grid_force


GRAVITY_N_PER_KG = 9.80665
SOURCE_ROOT = Path("tmp/hardware/force-calibration/20260722")
DATASETS: dict[str, dict[str, object]] = {
    "original-contact": {
        "baseline": "range-3p5-to-7/baseline/dop4864-parser-capture-20260723T014248Z.bin",
        "loads": [
            ("4.5", 4500, "range-3p5-to-7/4500g/dop4864-parser-capture-20260723T014524Z.bin"),
            ("5.5", 5500, "range-3p5-to-7/5500g/dop4864-parser-capture-20260723T014614Z.bin"),
            ("6.5", 6500, "range-3p5-to-7/6500g/dop4864-parser-capture-20260723T014716Z.bin"),
            ("7.5", 7500, "range-3p5-to-7p5/7500g/dop4864-parser-capture-20260723T014808Z.bin"),
            ("8.0", 8000, "range-3p5-to-8/8000g-repeat/dop4864-parser-capture-20260723T015039Z.bin"),
        ],
    },
    "small-contact": {
        "baseline": "small-contact/baseline/dop4864-parser-capture-20260723T021406Z.bin",
        "loads": [
            ("4.5", 4500, "small-contact/4500g/dop4864-parser-capture-20260723T021517Z.bin"),
            ("5.5", 5500, "small-contact/5500g/dop4864-parser-capture-20260723T021615Z.bin"),
            ("6.0", 6000, "small-contact/6000g/dop4864-parser-capture-20260723T021653Z.bin"),
            ("6.5", 6500, "small-contact/6500g/dop4864-parser-capture-20260723T021800Z.bin"),
            ("7.5", 7500, "small-contact/7500g/dop4864-parser-capture-20260723T021920Z.bin"),
            ("8.0", 8000, "small-contact/8000g/dop4864-parser-capture-20260723T022001Z.bin"),
        ],
    },
}
HUMAN_REPLAY = {
    "double-foot": (
        "human-69p8kg/baseline-repeat/dop4864-parser-capture-20260723T020042Z.bin",
        "human-69p8kg/double-foot/dop4864-parser-capture-20260723T020121Z.bin",
    ),
    "single-foot": (
        "human-69p8kg/single-foot-baseline/dop4864-parser-capture-20260723T020330Z.bin",
        "human-69p8kg/single-foot/dop4864-parser-capture-20260723T020408Z.bin",
    ),
}
HUMAN_REFERENCE_MASS_KG = 69.8


@dataclass(frozen=True, slots=True)
class CurveFit:
    model: str
    parameters: tuple[float, ...]


def prepare_loads(
    *, baseline_frames: np.ndarray, raw_loads: list[tuple[str, float, np.ndarray]], threshold_multiplier: float,
    subtract_threshold: bool = False,
) -> list[PreparedLoad]:
    """Build immutable-frame residuals under one activity/background policy."""

    baseline = np.median(baseline_frames, axis=0)
    baseline_mad = np.median(np.abs(baseline_frames - baseline), axis=0)
    threshold = np.maximum(1.0, threshold_multiplier * baseline_mad)
    medians = [np.maximum(np.median(frames, axis=0) - baseline, 0.0) for _, _, frames in raw_loads]
    union_active = np.any(np.stack([delta > threshold for delta in medians]), axis=0)
    if not union_active.any():
        raise ValueError("no active points")

    prepared = []
    for label, mass_g, frames in raw_loads:
        aggregate = np.sum(np.maximum(frames - baseline, 0.0)[:, union_active], axis=1)
        stable, _, _ = stable_mask(aggregate)
        delta = np.maximum(np.median(frames[stable], axis=0) - baseline, 0.0)
        active = delta > threshold
        if subtract_threshold:
            delta = np.maximum(delta - threshold, 0.0)
        prepared.append(
            PreparedLoad(
                label=label,
                mass_g=mass_g,
                target_force_n=mass_g / 1000.0 * GRAVITY_N_PER_KG,
                delta_count=delta,
                active=active,
                stable_frame_count=int(stable.sum()),
            )
        )
    return prepared


def _curve_force(model: str, parameters: tuple[float, ...], voltage: np.ndarray) -> np.ndarray:
    """Return point force in N; every listed model is positive and monotonic."""

    if model == "fixed-v0-power":
        log_gain, log_exponent = parameters
        z = voltage / (ADC_REFERENCE_V - voltage)
        return np.exp(log_gain) * z ** np.exp(log_exponent)
    if model == "free-v0-power":
        log_gain, log_exponent, v0_v = parameters
        z = voltage / (v0_v - voltage)
        return np.exp(log_gain) * z ** np.exp(log_exponent)
    if model == "two-slope-monotonic":
        log_gain, log_low_slope, log_high_slope, knot = parameters
        z = voltage / (ADC_REFERENCE_V - voltage)
        log_z = np.log(z)
        low = np.exp(log_low_slope)
        high = np.exp(log_high_slope)
        log_force = log_gain + low * np.minimum(log_z, knot) + high * np.maximum(log_z - knot, 0.0)
        return np.exp(log_force)
    if model == "saturating-hill":
        log_max_force, log_half_ratio, log_exponent = parameters
        z = voltage / (ADC_REFERENCE_V - voltage)
        maximum = np.exp(log_max_force)
        half_ratio = np.exp(log_half_ratio)
        exponent = np.exp(log_exponent)
        return maximum * z**exponent / (half_ratio**exponent + z**exponent)
    raise ValueError(f"unsupported model: {model}")


def _initial_parameters(model: str, loads: list[PreparedLoad]) -> tuple[np.ndarray, tuple[np.ndarray, np.ndarray]]:
    all_active_voltage = np.concatenate(
        [load.delta_count[load.active] * ADC_REFERENCE_V / ADC_MAX_CODE for load in loads]
    )
    max_voltage = float(np.max(all_active_voltage))
    ratios = all_active_voltage / (ADC_REFERENCE_V - all_active_voltage)
    knot = float(np.median(np.log(ratios)))
    if model == "fixed-v0-power":
        return np.asarray([0.0, log(1.0)]), (np.asarray([-20.0, log(0.03)]), np.asarray([20.0, log(10.0)]))
    if model == "free-v0-power":
        return np.asarray([0.0, log(1.0), ADC_REFERENCE_V]), (
            np.asarray([-20.0, log(0.03), max_voltage + 0.01]),
            np.asarray([20.0, log(10.0), 6.0]),
        )
    if model == "two-slope-monotonic":
        return np.asarray([0.0, log(1.0), log(1.0), knot]), (
            np.asarray([-20.0, log(0.03), log(0.03), knot - 1e-12]),
            np.asarray([20.0, log(10.0), log(10.0), knot + 1e-12]),
        )
    if model == "saturating-hill":
        return np.asarray([log(20.0), log(0.5), log(1.0)]), (
            np.asarray([log(0.01), log(1e-4), log(0.03)]),
            np.asarray([log(1e6), log(1e3), log(10.0)]),
        )
    raise ValueError(model)


def predicted_force(load: PreparedLoad, fit: CurveFit) -> float:
    voltage = load.delta_count * ADC_REFERENCE_V / ADC_MAX_CODE
    force = np.zeros_like(voltage)
    valid = load.active & (voltage > 0.0)
    force[valid] = _curve_force(fit.model, fit.parameters, voltage[valid])
    return integrate_regular_grid_force(
        force_n=tuple(float(value) for value in force.reshape(-1, order="F")),
        active=tuple(bool(value) for value in load.active.reshape(-1, order="F")),
        rows=ROWS,
        columns=COLUMNS,
        pitch_x_mm=PITCH_X_MM,
        pitch_y_mm=PITCH_Y_MM,
        sensor_area_mm2=SENSOR_AREA_MM2,
    ).integrated_force_n


def fit_curve(model: str, loads: list[PreparedLoad]) -> CurveFit:
    initial, bounds = _initial_parameters(model, loads)

    def residual(parameters: np.ndarray) -> np.ndarray:
        fit = CurveFit(model, tuple(float(value) for value in parameters))
        return np.asarray(
            [(predicted_force(load, fit) - load.target_force_n) / load.target_force_n for load in loads]
        )

    result = least_squares(residual, initial, bounds=bounds, max_nfev=3_000)
    if not result.success:
        raise RuntimeError(f"{model}: {result.message}")
    return CurveFit(model, tuple(float(value) for value in result.x))


def leave_one_out(loads: list[PreparedLoad], model: str) -> dict[str, object]:
    errors = []
    parameters = []
    for index, held_out in enumerate(loads):
        fit = fit_curve(model, loads[:index] + loads[index + 1 :])
        predicted_n = predicted_force(held_out, fit)
        error = (predicted_n - held_out.target_force_n) / held_out.target_force_n * 100.0
        errors.append(
            {
                "label": held_out.label,
                "target_mass_kg": held_out.mass_g / 1000.0,
                "inferred_mass_kg": predicted_n / GRAVITY_N_PER_KG,
                "error_percent": error,
            }
        )
        parameters.append(fit.parameters)
    absolute_errors = [abs(item["error_percent"]) for item in errors]
    return {
        "model": model,
        "mean_absolute_error_percent": float(np.mean(absolute_errors)),
        "maximum_absolute_error_percent": float(np.max(absolute_errors)),
        "folds": errors,
        "fold_parameters": parameters,
    }


def load_dataset(name: str) -> tuple[np.ndarray, list[tuple[str, float, np.ndarray]]]:
    dataset = DATASETS[name]
    baseline = decode_capture(SOURCE_ROOT / str(dataset["baseline"]))
    loads = [
        (label, mass_g, decode_capture(SOURCE_ROOT / path))
        for label, mass_g, path in dataset["loads"]  # type: ignore[index]
    ]
    return baseline, loads


def benchmark(name: str) -> dict[str, object]:
    baseline, raw_loads = load_dataset(name)
    default_loads = prepare_loads(
        baseline_frames=baseline, raw_loads=raw_loads, threshold_multiplier=3.0
    )
    curve_results = [
        leave_one_out(default_loads, model)
        for model in ("fixed-v0-power", "free-v0-power", "two-slope-monotonic", "saturating-hill")
    ]
    processing_results = []
    for multiplier, subtract_threshold in ((1.0, False), (2.0, False), (3.0, False), (5.0, False), (3.0, True)):
        loads = prepare_loads(
            baseline_frames=baseline,
            raw_loads=raw_loads,
            threshold_multiplier=multiplier,
            subtract_threshold=subtract_threshold,
        )
        result = leave_one_out(loads, "fixed-v0-power")
        result["threshold_multiplier"] = multiplier
        result["subtract_threshold"] = subtract_threshold
        processing_results.append(result)
    return {
        "dataset": name,
        "method": "leave-one-load-out; coefficients re-fit inside each fold; raw frames unchanged",
        "curve_results": curve_results,
        "processing_results": processing_results,
    }


def unified_candidate_with_human_replay() -> dict[str, object]:
    """Select one curve from combined known loads, then replay untouched human frames."""

    original_baseline, original_raw = load_dataset("original-contact")
    small_baseline, small_raw = load_dataset("small-contact")
    original = prepare_loads(
        baseline_frames=original_baseline, raw_loads=original_raw, threshold_multiplier=3.0
    )
    small = prepare_loads(
        baseline_frames=small_baseline, raw_loads=small_raw, threshold_multiplier=3.0
    )
    combined = original + small
    candidates = [
        leave_one_out(combined, model)
        for model in ("fixed-v0-power", "free-v0-power", "two-slope-monotonic", "saturating-hill")
    ]
    selected = min(candidates, key=lambda result: float(result["mean_absolute_error_percent"]))
    fit = fit_curve(str(selected["model"]), combined)
    replay = {}
    for label, (baseline_path, load_path) in HUMAN_REPLAY.items():
        prepared = prepare_loads(
            baseline_frames=decode_capture(SOURCE_ROOT / baseline_path),
            raw_loads=[(label, HUMAN_REFERENCE_MASS_KG * 1000.0, decode_capture(SOURCE_ROOT / load_path))],
            threshold_multiplier=3.0,
        )[0]
        inferred_mass_kg = predicted_force(prepared, fit) / GRAVITY_N_PER_KG
        replay[label] = {
            "inferred_mass_kg": inferred_mass_kg,
            "error_percent": (inferred_mass_kg / HUMAN_REFERENCE_MASS_KG - 1.0) * 100.0,
            "active_sensor_count": int(prepared.active.sum()),
            "stable_frame_count": prepared.stable_frame_count,
        }
    return {
        "selection_method": "combined A+B leave-one-load-out MAE; human data excluded from selection",
        "candidate_results": candidates,
        "selected_model": fit.model,
        "selected_parameters": fit.parameters,
        "human_replay": replay,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", choices=sorted(DATASETS), action="append")
    args = parser.parse_args()
    datasets = args.dataset or sorted(DATASETS)
    print(
        json.dumps(
            {"separate_datasets": [benchmark(name) for name in datasets], "unified_candidate": unified_candidate_with_human_replay()},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
