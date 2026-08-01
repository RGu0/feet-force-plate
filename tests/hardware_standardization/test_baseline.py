from __future__ import annotations

import pytest

from client.hardware_standardization.baseline import apply_zero_reference, build_baseline_reference
from client.hardware_standardization.models import BaselineSample, UnloadedBaselineWindow


def _window() -> UnloadedBaselineWindow:
    return UnloadedBaselineWindow(
        schema_version="unloaded-baseline-window/1",
        baseline_window_id="baseline-1",
        validation_run_id="validation-1",
        validation_outcome="PASS",
        layout_digest="layout-digest",
        rules_version="startup-baseline/1",
        threshold_version="startup-baseline-thresholds/1",
        source_digest="a" * 64,
        samples=(
            BaselineSample(0, (10, 20)),
            BaselineSample(2_000_000_000, (12, 18)),
            BaselineSample(5_000_000_000, (11, 22)),
        ),
    )


def test_baseline_uses_per_cell_median_and_mad_without_mutating_samples() -> None:
    window = _window()

    reference = build_baseline_reference(window, minimum_duration_ns=5_000_000_000)

    assert reference.zero_offset_count == (11.0, 20.0)
    assert reference.noise_mad_count == (1.0, 2.0)
    assert window.samples[0].values == (10, 20)


def test_zero_reference_preserves_signed_residual_and_nonnegative_relative_load() -> None:
    corrected = apply_zero_reference(
        (15, 18), build_baseline_reference(_window(), minimum_duration_ns=5_000_000_000)
    )

    assert corrected.zero_corrected_count == (4.0, -2.0)
    assert corrected.relative_load_count == (4.0, 0.0)
    assert "ZERO_OFFSET_APPLIED" in corrected.quality_flags


def test_baseline_rejects_failed_or_incomplete_window() -> None:
    failed = UnloadedBaselineWindow(
        schema_version="unloaded-baseline-window/1",
        baseline_window_id="baseline-2",
        validation_run_id="validation-2",
        validation_outcome="RETRYABLE_FAIL",
        layout_digest="layout-digest",
        rules_version="startup-baseline/1",
        threshold_version="startup-baseline-thresholds/1",
        source_digest="b" * 64,
        samples=(BaselineSample(0, (1,)), BaselineSample(5_000_000_000, (1,))),
    )

    with pytest.raises(ValueError, match="PASS"):
        build_baseline_reference(failed, minimum_duration_ns=5_000_000_000)
