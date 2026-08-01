"""Zero-reference derivation from a qualifying immutable unloaded window."""

from __future__ import annotations

from statistics import median

from .models import BaselineReference, UnloadedBaselineWindow, ZeroCorrectedValues


def build_baseline_reference(
    window: UnloadedBaselineWindow, *, minimum_duration_ns: int
) -> BaselineReference:
    """Derive per-cell median offset and median absolute deviation in raw counts."""

    if window.validation_outcome != "PASS":
        raise ValueError("baseline validation outcome must be PASS")
    if minimum_duration_ns <= 0:
        raise ValueError("minimum baseline duration must be positive")
    if window.duration_ns < minimum_duration_ns:
        raise ValueError("baseline window does not meet the device minimum duration")
    columns = tuple(zip(*(sample.values for sample in window.samples), strict=True))
    zero_offset = tuple(float(median(values)) for values in columns)
    noise_mad = tuple(
        float(median(abs(value - centre) for value in values))
        for values, centre in zip(columns, zero_offset, strict=True)
    )
    return BaselineReference(
        schema_version="baseline-reference/1",
        baseline_window_id=window.baseline_window_id,
        layout_digest=window.layout_digest,
        zero_offset_count=zero_offset,
        noise_mad_count=noise_mad,
        rules_version=window.rules_version,
        threshold_version=window.threshold_version,
        source_digest=window.source_digest,
    )


def apply_zero_reference(
    raw_count: tuple[int | float, ...], reference: BaselineReference
) -> ZeroCorrectedValues:
    """Keep signed residuals and expose a separate non-negative relative load."""

    if len(raw_count) != len(reference.zero_offset_count):
        raise ValueError("raw_count length must match baseline reference")
    corrected = tuple(
        float(raw) - offset
        for raw, offset in zip(raw_count, reference.zero_offset_count, strict=True)
    )
    return ZeroCorrectedValues(
        zero_corrected_count=corrected,
        relative_load_count=tuple(max(value, 0.0) for value in corrected),
        quality_flags=frozenset({"ZERO_OFFSET_APPLIED"}),
    )
