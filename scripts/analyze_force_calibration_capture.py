"""Analyze local force-validation captures without changing serial parsing behavior."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from client.device.protocol import DaoOneP4864Parser, ProtocolProfile
from client.hardware_standardization.calibration import VoltageToForceModel


GRAVITY_M_S2 = 9.80665
SENSOR_DIAMETER_MM = 6.0
SENSOR_AREA_MM2 = np.pi * (SENSOR_DIAMETER_MM / 2.0) ** 2
LOAD_CONTACT_DIAMETER_MM = 57.0
LOAD_CONTACT_AREA_MM2 = np.pi * (LOAD_CONTACT_DIAMETER_MM / 2.0) ** 2


def decode_capture(path: Path) -> np.ndarray:
    parser = DaoOneP4864Parser(
        ProtocolProfile.observed_compact_8bit(
            version="do-p4864/observed-compact-column-major-48x64-20260721"
        ),
        allow_unverified=True,
    )
    frames = parser.feed(path.read_bytes())
    if not frames:
        raise ValueError(f"no decoded frames in {path}")
    return np.stack([frame.values for frame in frames]).astype(np.float64, copy=False)


def stable_mask(values: np.ndarray) -> tuple[np.ndarray, float, float]:
    median = float(np.median(values))
    mad = float(np.median(np.abs(values - median)))
    tolerance = max(1.0, 3.0 * mad)
    return np.abs(values - median) <= tolerance, median, mad


def force_n(model: VoltageToForceModel, delta_count: float) -> float | None:
    return model.force_from_voltage(max(model.signed_count_to_voltage(delta_count), 0.0))


def analyze(
    *, baseline_frames: np.ndarray, loads: list[tuple[str, float, np.ndarray]]
) -> dict[str, object]:
    baseline = np.median(baseline_frames, axis=0)
    baseline_mad = np.median(np.abs(baseline_frames - baseline), axis=0)
    load_medians = [np.median(frames, axis=0) for _, _, frames in loads]
    response_threshold = np.maximum(1.0, 3.0 * baseline_mad)
    initial_delta = np.maximum(load_medians[0] - baseline, 0.0)
    initial_active_mask = initial_delta > response_threshold
    if not initial_active_mask.any():
        row, column = np.unravel_index(np.argmax(initial_delta), initial_delta.shape)
        raise ValueError(
            "the initial load did not identify any active sensors; "
            f"maximum median delta was {initial_delta[row, column]:.3f} counts at "
            f"row={row}, column={column}; baseline MAD there was "
            f"{baseline_mad[row, column]:.3f} counts"
        )
    union_active_mask = np.any(
        np.stack(
            [np.maximum(load_median - baseline, 0.0) > response_threshold for load_median in load_medians]
        ),
        axis=0,
    )
    model = VoltageToForceModel(
        adc_bit_depth=8,
        adc_reference_voltage_v=4.096,
        r0=2.2,
        alpha=0.751,
        beta=2.657,
    )
    records: list[dict[str, object]] = []
    for label, mass_g, frames in loads:
        aggregate_delta = np.sum(
            np.maximum(frames - baseline, 0.0)[:, union_active_mask], axis=1
        )
        mask, aggregate_median, aggregate_mad = stable_mask(aggregate_delta)
        per_cell_delta = np.maximum(np.median(frames[mask], axis=0) - baseline, 0.0)
        current_active_mask = per_cell_delta > response_threshold
        active_deltas = per_cell_delta[current_active_mask]
        active_forces = [force_n(model, float(value)) for value in active_deltas]
        total_force = float(sum(value for value in active_forces if value is not None))
        saturated_sensor_count = sum(value is None for value in active_forces)
        local_peak_row, local_peak_column = np.unravel_index(
            np.argmax(per_cell_delta), per_cell_delta.shape
        )
        top_indices = np.argsort(per_cell_delta.ravel())[-5:][::-1]
        top_cells = []
        for flat_index in top_indices:
            row, column = np.unravel_index(flat_index, per_cell_delta.shape)
            top_cells.append(
                {
                    "row": int(row),
                    "column": int(column),
                    "delta_count": float(per_cell_delta[row, column]),
                    "provisional_force_n": force_n(model, float(per_cell_delta[row, column])),
                }
            )
        target_force = mass_g / 1000.0 * GRAVITY_M_S2
        records.append(
            {
                "label": label,
                "mass_g": mass_g,
                "target_force_n": target_force,
                "local_peak_cell": {
                    "row": int(local_peak_row),
                    "column": int(local_peak_column),
                },
                "top_cells_by_delta_count": top_cells,
                "stable_frame_count": int(mask.sum()),
                "decoded_frame_count": int(frames.shape[0]),
                "active_sensor_aggregate_delta_count_median": aggregate_median,
                "active_sensor_aggregate_delta_count_mad": aggregate_mad,
                "provisional_total_force_n": total_force,
                "provisional_average_sensor_pressure_n_per_mm2": total_force
                / (int(current_active_mask.sum()) * SENSOR_AREA_MM2),
                "provisional_average_sensor_pressure_pa": total_force
                / (int(current_active_mask.sum()) * SENSOR_AREA_MM2)
                * 1_000_000,
                "provisional_average_load_contact_pressure_n_per_mm2": total_force
                / LOAD_CONTACT_AREA_MM2,
                "inferred_mass_kg": total_force / GRAVITY_M_S2,
                "force_error_n": total_force - target_force,
                "force_error_percent": (total_force - target_force) / target_force * 100.0,
                "saturated_active_sensor_count": saturated_sensor_count,
                "active_sensor_count": int(current_active_mask.sum()),
            }
        )
    return {
        "method": {
            "baseline": "per-cell median across unloaded capture",
            "stable_selection": "active-sensor aggregate values within max(1 count, 3*MAD) of median",
            "active_sensor_selection": "all-load response union for stability; each load uses points above max(1 count, 3*baseline MAD) for force/pressure",
            "adc_voltage": "count / 255 * 4.096 V",
            "force_model": "(10^2.657 * delta_v / 2.2 / (4.096 - delta_v))^(1/0.751) / 1000 N",
            "sensor_area_assumption_mm2": SENSOR_AREA_MM2,
            "load_contact_area_mm2": LOAD_CONTACT_AREA_MM2,
        },
        "baseline_decoded_frame_count": int(baseline_frames.shape[0]),
        "initial_3p5kg_active_sensor_count": int(initial_active_mask.sum()),
        "all_loads_union_active_sensor_count": int(union_active_mask.sum()),
        "loads": records,
    }


def _load_argument(value: str) -> tuple[str, float, Path]:
    label, mass_g, path = value.split(":", maxsplit=2)
    return label, float(mass_g), Path(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--load", action="append", type=_load_argument, required=True)
    args = parser.parse_args()
    result = analyze(
        baseline_frames=decode_capture(args.baseline),
        loads=[(label, mass_g, decode_capture(path)) for label, mass_g, path in args.load],
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
