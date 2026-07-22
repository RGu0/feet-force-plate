from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FeatureParameters:
    """Versioned engineering parameters for physical static-balance features."""

    version: str = "static-balance-feature-parameters/1.0"
    minimum_total_force_n: float = 50.0
    contact_cell_force_threshold_n: float = 1.0
    despike_window_samples: int = 3
    lowpass_order: int = 4
    lowpass_cutoff_hz: float = 5.0
    maximum_gap_nominal_intervals: float = 2.0
    ratio_epsilon: float = 1e-9

    def __post_init__(self) -> None:
        if not self.version.strip():
            raise ValueError("feature parameter version is required")
        if self.minimum_total_force_n <= 0:
            raise ValueError("minimum_total_force_n must be positive")
        if self.contact_cell_force_threshold_n < 0:
            raise ValueError("contact_cell_force_threshold_n cannot be negative")
        if self.despike_window_samples < 1 or self.despike_window_samples % 2 == 0:
            raise ValueError("despike_window_samples must be a positive odd number")
        if self.lowpass_order < 1:
            raise ValueError("lowpass_order must be positive")
        if self.lowpass_cutoff_hz < 0:
            raise ValueError("lowpass_cutoff_hz cannot be negative")
        if self.maximum_gap_nominal_intervals < 1:
            raise ValueError("maximum_gap_nominal_intervals must be at least one")
        if self.ratio_epsilon <= 0:
            raise ValueError("ratio_epsilon must be positive")
