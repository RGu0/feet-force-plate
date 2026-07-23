from __future__ import annotations

import numpy as np

from scripts.benchmark_force_calibration_variants import _curve_force


def test_all_candidate_response_curves_are_monotonic_over_the_observed_voltage_domain() -> None:
    voltage = np.linspace(0.05, 3.6, 100)
    candidates = (
        ("fixed-v0-power", (0.0, 0.0)),
        ("free-v0-power", (0.0, 0.0, 4.2)),
        ("two-slope-monotonic", (0.0, 0.0, 0.0, -1.0)),
        ("saturating-hill", (3.0, -1.0, 0.0)),
    )

    for model, parameters in candidates:
        assert np.all(np.diff(_curve_force(model, parameters, voltage)) > 0)
