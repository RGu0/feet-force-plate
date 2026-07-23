"""Render the unified A+B calibration curve and known-load/human validation plot."""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from scripts.benchmark_force_calibration_variants import (
    ADC_MAX_CODE,
    ADC_REFERENCE_V,
    CurveFit,
    HUMAN_REFERENCE_MASS_KG,
    HUMAN_REPLAY,
    SOURCE_ROOT,
    _curve_force,
    decode_capture,
    load_dataset,
    predicted_force,
    prepare_loads,
    unified_candidate_with_human_replay,
)
from scripts.fit_bounded_voltage_force_model import SENSOR_AREA_MM2


def build_figure(output: Path) -> None:
    candidate = unified_candidate_with_human_replay()
    fit = CurveFit(
        str(candidate["selected_model"]),
        tuple(float(value) for value in candidate["selected_parameters"]),
    )
    points: list[dict[str, object]] = []
    response_samples: list[dict[str, object]] = []
    for dataset, color, marker in (
        ("original-contact", "#1769aa", "o"),
        ("small-contact", "#c87917", "s"),
    ):
        baseline, raw_loads = load_dataset(dataset)
        loads = prepare_loads(
            baseline_frames=baseline, raw_loads=raw_loads, threshold_multiplier=3.0
        )
        for load in loads:
            volts = load.delta_count[load.active] * ADC_REFERENCE_V / ADC_MAX_CODE
            total_force_n = predicted_force(load, fit)
            point_force = _curve_force(fit.model, fit.parameters, volts)
            left = volts <= ADC_REFERENCE_V * np.exp(fit.parameters[3]) / (1.0 + np.exp(fit.parameters[3]))
            response_samples.extend(
                {
                    "group": dataset,
                    "voltage": float(voltage),
                    "force": float(force),
                    "color": color,
                }
                for voltage, force in zip(volts, point_force, strict=True)
            )
            points.append(
                {
                    "group": dataset,
                    "actual": load.mass_g / 1000.0,
                    "estimated": total_force_n / 9.80665,
                    "mean_pressure_kpa": total_force_n / (load.active.sum() * SENSOR_AREA_MM2) * 1000.0,
                    "color": color,
                    "marker": marker,
                    "label": f"{load.mass_g / 1000.0:g} kg",
                }
            )

    human = candidate["human_replay"]
    for label, record in human.items():
        baseline_path, load_path = HUMAN_REPLAY[label]
        human_load = prepare_loads(
            baseline_frames=decode_capture(SOURCE_ROOT / baseline_path),
            raw_loads=[(label, HUMAN_REFERENCE_MASS_KG * 1000.0, decode_capture(SOURCE_ROOT / load_path))],
            threshold_multiplier=3.0,
        )[0]
        human_voltage = human_load.delta_count[human_load.active] * ADC_REFERENCE_V / ADC_MAX_CODE
        human_force = _curve_force(fit.model, fit.parameters, human_voltage)
        color = "#9c2f50" if label == "double-foot" else "#5f6b76"
        response_samples.extend(
            {
                "group": label,
                "voltage": float(voltage),
                "force": float(force),
                "color": color,
            }
            for voltage, force in zip(human_voltage, human_force, strict=True)
        )
        points.append(
            {
                "group": label,
                "actual": HUMAN_REFERENCE_MASS_KG,
                "estimated": float(record["inferred_mass_kg"]),
                "mean_pressure_kpa": float(record["inferred_mass_kg"])
                * 9.80665
                / (int(record["active_sensor_count"]) * SENSOR_AREA_MM2)
                * 1000.0,
                "color": color,
                "marker": "D" if label == "double-foot" else "^",
                "label": "真人双脚" if label == "double-foot" else "真人单脚",
            }
        )

    plt.rcParams.update(
        {
            "font.family": ["PingFang SC", "Arial Unicode MS", "DejaVu Sans"],
            "axes.unicode_minus": False,
            "font.size": 10,
        }
    )
    figure, (mass_axis, pressure_axis, response_axis) = plt.subplots(1, 3, figsize=(20, 6.7), dpi=220)
    figure.patch.set_facecolor("white")

    mass_axis.set_title("系统级实测验证：真实质量与还原质量", loc="left", fontweight="bold", pad=18)
    mass_axis.plot([0, 75], [0, 75], color="#263238", linewidth=1.5, label="理想还原 y=x")
    for group, label, color, marker in (
        ("original-contact", "A 组砝码", "#1769aa", "o"),
        ("small-contact", "B 组砝码", "#c87917", "s"),
    ):
        group_points = sorted(
            [point for point in points if point["group"] == group], key=lambda point: float(point["actual"])
        )
        mass_axis.plot(
            [float(point["actual"]) for point in group_points],
            [float(point["estimated"]) for point in group_points],
            color=color,
            linewidth=1.1,
            alpha=0.6,
        )
        mass_axis.scatter(
            [float(point["actual"]) for point in group_points],
            [float(point["estimated"]) for point in group_points],
            s=44,
            color=color,
            edgecolor="white",
            linewidth=0.8,
            marker=marker,
            label=label,
            zorder=3,
        )
    for group, label in (("double-foot", "真人双脚 68.79 kg"), ("single-foot", "真人单脚 56.79 kg")):
        point = next(point for point in points if point["group"] == group)
        mass_axis.scatter(
            float(point["actual"]),
            float(point["estimated"]),
            s=75,
            color=str(point["color"]),
            edgecolor="#263238",
            linewidth=0.8,
            marker=str(point["marker"]),
            label=label,
            zorder=4,
        )
        mass_axis.annotate(
            label,
            (float(point["actual"]), float(point["estimated"])),
            xytext=(-92, 8 if group == "double-foot" else -16),
            textcoords="offset points",
            fontsize=8.5,
            color=str(point["color"]),
            fontweight="bold",
        )
    mass_axis.set_xlim(0, 75)
    mass_axis.set_ylim(0, 75)
    mass_axis.set_aspect("equal", adjustable="box")
    mass_axis.set_xlabel("真实总质量（kg）")
    mass_axis.set_ylabel("空间积分后还原总质量（kg）")
    mass_axis.grid(color="#d7dde1", linewidth=0.7)
    mass_axis.legend(loc="lower right", frameon=False, fontsize=8)

    inset = mass_axis.inset_axes([0.07, 0.56, 0.42, 0.36])
    inset.plot([3.2, 8.5], [3.2, 8.5], color="#263238", linewidth=1.0)
    for group, color, marker in (
        ("original-contact", "#1769aa", "o"),
        ("small-contact", "#c87917", "s"),
    ):
        group_points = sorted(
            [point for point in points if point["group"] == group], key=lambda point: float(point["actual"])
        )
        inset.plot(
            [float(point["actual"]) for point in group_points],
            [float(point["estimated"]) for point in group_points],
            color=color,
            linewidth=0.8,
            alpha=0.65,
        )
        inset.scatter(
            [float(point["actual"]) for point in group_points],
            [float(point["estimated"]) for point in group_points],
            s=20,
            color=color,
            edgecolor="white",
            linewidth=0.5,
            marker=marker,
            zorder=3,
        )
    inset.set_xlim(3.2, 8.5)
    inset.set_ylim(3.2, 8.5)
    inset.set_title("砝码区放大", fontsize=7.5, pad=3)
    inset.grid(color="#d7dde1", linewidth=0.45)
    inset.tick_params(labelsize=6)

    pressure_axis.set_title("受力工况对比：质量与候选平均接触压强", loc="left", fontweight="bold", pad=18)
    for group, label, color, marker in (
        ("original-contact", "A 组砝码", "#1769aa", "o"),
        ("small-contact", "B 组砝码", "#c87917", "s"),
    ):
        group_points = sorted(
            [point for point in points if point["group"] == group], key=lambda point: float(point["actual"])
        )
        pressure_axis.plot(
            [float(point["actual"]) for point in group_points],
            [float(point["mean_pressure_kpa"]) for point in group_points],
            color=color,
            linewidth=1.2,
            alpha=0.7,
        )
        pressure_axis.scatter(
            [float(point["actual"]) for point in group_points],
            [float(point["mean_pressure_kpa"]) for point in group_points],
            s=42,
            color=color,
            edgecolor="white",
            linewidth=0.8,
            marker=marker,
            label=label,
            zorder=3,
        )
    for group, label in (("double-foot", "真人双脚 50.8 kPa"), ("single-foot", "真人单脚 66.1 kPa")):
        point = next(point for point in points if point["group"] == group)
        pressure_axis.scatter(
            float(point["actual"]),
            float(point["mean_pressure_kpa"]),
            s=75,
            color=str(point["color"]),
            edgecolor="#263238",
            linewidth=0.8,
            marker=str(point["marker"]),
            label=label,
            zorder=4,
        )
        pressure_axis.annotate(
            label,
            (float(point["actual"]), float(point["mean_pressure_kpa"])),
            xytext=(-98, 7 if group == "double-foot" else -15),
            textcoords="offset points",
            fontsize=8,
            color=str(point["color"]),
            fontweight="bold",
        )
    pressure_axis.set_xlabel("真实总质量（kg）")
    pressure_axis.set_ylabel("候选平均接触压强（kPa）")
    pressure_axis.set_xlim(0, 75)
    pressure_axis.set_ylim(30, 90)
    pressure_axis.grid(color="#d7dde1", linewidth=0.7)
    pressure_axis.legend(loc="lower right", frameon=False, fontsize=8)

    response_axis.set_title("统一点级电压–力候选曲线", loc="left", fontweight="bold", pad=18)
    voltages = np.asarray([float(sample["voltage"]) for sample in response_samples])
    minimum_voltage = max(0.01, float(np.min(voltages)) * 0.8)
    maximum_voltage = float(np.max(voltages)) * 1.02
    voltage = np.linspace(minimum_voltage, maximum_voltage, 500)
    force = _curve_force(fit.model, fit.parameters, voltage)
    response_axis.plot(voltage, force, color="#1769aa", linewidth=2.4, label="统一双斜率单调曲线")
    knot_ratio = float(np.exp(fit.parameters[3]))
    knot_voltage = ADC_REFERENCE_V * knot_ratio / (1.0 + knot_ratio)
    response_axis.axvline(knot_voltage, color="#c87917", linewidth=1.2, linestyle="--", label="分段点")
    for group, label, color in (
        ("original-contact", "A 组活动点", "#1769aa"),
        ("small-contact", "B 组活动点", "#c87917"),
        ("double-foot", "人体双脚活动点", "#9c2f50"),
        ("single-foot", "人体单脚活动点", "#5f6b76"),
    ):
        group_samples = [sample for sample in response_samples if sample["group"] == group]
        response_axis.scatter(
            [float(sample["voltage"]) for sample in group_samples],
            [float(sample["force"]) for sample in group_samples],
            color=color,
            alpha=0.13,
            s=9,
            edgecolor="none",
            label="_nolegend_",
            zorder=2,
        )
    response_axis.text(
        0.05,
        0.82,
        "左段主力\nA 4.5 kg：96% 候选力\nΔV ≤ 1.381 V",
        transform=response_axis.transAxes,
        fontsize=8,
        color="#1769aa",
        bbox={"boxstyle": "round,pad=0.3", "facecolor": "white", "edgecolor": "#1769aa", "alpha": 0.9},
    )
    response_axis.text(
        0.58,
        0.34,
        "右段主力\nA 5.5–8.0 kg：60–74%\nB 4.5–8.0 kg：73–79%\nΔV > 1.381 V",
        transform=response_axis.transAxes,
        fontsize=8,
        color="#9c5b0c",
        bbox={"boxstyle": "round,pad=0.3", "facecolor": "white", "edgecolor": "#c87917", "alpha": 0.9},
    )
    response_axis.set_xlabel("零校正电压 ΔV（V）")
    response_axis.set_ylabel("候选单点法向力（N）")
    response_axis.set_ylim(bottom=-0.07)
    response_axis.grid(color="#d7dde1", linewidth=0.7)
    response_axis.legend(loc="lower right", frameon=False, fontsize=8)

    figure.suptitle("DP-P4864 统一砝码拟合与实测验证（2026-07-22）", x=0.06, y=0.965, ha="left", fontsize=15, fontweight="bold")
    figure.text(
        0.06,
        0.925,
        "砝码点为统一曲线拟合样本；人体点为未参与选曲的第三组独立验证。深灰线为理想 y=x；压强为候选活动面积平均值。",
        color="#52616b",
        fontsize=9,
    )
    figure.text(
        0.06,
        0.01,
        "注：该曲线为硬件层 provisional 候选；单脚验证仍有 −18.64% 误差，不能作为已完成的力标定。",
        color="#52616b",
        fontsize=8.5,
    )
    figure.tight_layout(rect=(0.03, 0.04, 0.99, 0.85))
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, facecolor="white")
    plt.close(figure)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    build_figure(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
