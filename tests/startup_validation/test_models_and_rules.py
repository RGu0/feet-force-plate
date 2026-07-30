from __future__ import annotations

from dataclasses import asdict

import numpy as np

from client.device.protocol import RawFrame
from client.startup_validation.models import (
    DeviceValidationRun,
    ValidationOutcome,
    ValidationReason,
    ValidationStatistics,
)
from client.startup_validation.rules import (
    ValidationThresholds,
    evaluate_baseline,
)


def _frame(values: np.ndarray, timestamp_ns: int, source_index: int) -> RawFrame:
    immutable = np.asarray(values, dtype=np.uint8).copy()
    immutable.setflags(write=False)
    return RawFrame(
        values=immutable,
        host_monotonic_ns=timestamp_ns,
        host_wall_time_ns=1_800_000_000_000_000_000 + timestamp_ns,
        source_index=source_index,
        device_frame_seq=None,
        device_timestamp_ns=None,
        quality_flags=frozenset(
            {
                "CHECKSUM_NOT_ENFORCED",
            }
        ),
    )


def _healthy_frames(*, count: int = 101, period_ns: int = 50_000_000) -> tuple[RawFrame, ...]:
    rows, columns = np.indices((48, 64))
    return tuple(
        _frame((rows + columns + index) % 3, index * period_ns, index)
        for index in range(count)
    )


def _statistics(frames: tuple[RawFrame, ...]) -> ValidationStatistics:
    return ValidationStatistics.from_frames(
        frames,
        invalid_candidate_count=3,
        resynchronization_count=2,
    )


def _reasons(frames: tuple[RawFrame, ...]) -> tuple[ValidationReason, ...]:
    return evaluate_baseline(frames, _statistics(frames), ValidationThresholds()).reasons


def test_run_is_versioned_auditable_and_contains_no_raw_frame_payload() -> None:
    frames = _healthy_frames()
    statistics = _statistics(frames)
    run = DeviceValidationRun(
        validation_run_id="validation-run-1",
        previous_validation_run_id=None,
        terminal_id="terminal-opaque-1",
        device_ref="device-port-hash-1",
        attempt_number=1,
        app_version="0.1.0",
        protocol_version="do-p4864/observed-compact-1",
        data_mode_version="48x64-uint8-column-major/1",
        rules_version="startup-baseline/1",
        threshold_version="startup-baseline-thresholds/1",
        started_at_wall_ns=1_800_000_000_000_000_000,
        completed_at_wall_ns=1_800_000_006_000_000_000,
        outcome=ValidationOutcome.PASS,
        reason=None,
        error_code=None,
        diagnostic_id="diagnostic-opaque-1",
        statistics=statistics,
        transition_names=(
            "BOOTSTRAPPING",
            "CONNECTING",
            "WAITING_FOR_EMPTY",
            "COLLECTING_BASELINE",
            "VALIDATING",
            "PASSED",
        ),
    )

    assert run.schema_version == "device-validation-run/1"
    summary = run.safe_summary()
    encoded = repr(summary).lower()
    assert "values" not in encoded
    assert "raw_frame" not in encoded
    assert "threshold_values" not in encoded
    assert summary["versions"]["threshold"] == "startup-baseline-thresholds/1"
    assert summary["statistics"]["valid_frame_count"] == len(frames)
    assert summary["statistics"]["duration_ns"] >= 5_000_000_000
    assert asdict(run)["outcome"] is ValidationOutcome.PASS


def test_healthy_unloaded_window_passes_without_claiming_physical_units() -> None:
    frames = _healthy_frames()

    evaluation = evaluate_baseline(
        frames,
        _statistics(frames),
        ValidationThresholds(),
    )

    assert evaluation.reasons == ()
    assert evaluation.outcome is ValidationOutcome.PASS
    assert evaluation.unit == "raw_count"


def test_rule_engine_rejects_low_rate_and_large_host_gap() -> None:
    low_rate = _healthy_frames(count=11, period_ns=500_000_000)
    gap_frames = list(_healthy_frames())
    for index in range(51, len(gap_frames)):
        original = gap_frames[index]
        gap_frames[index] = _frame(
            original.values,
            original.host_monotonic_ns + 400_000_000,
            original.source_index,
        )

    assert ValidationReason.RATE_OUT_OF_RANGE in _reasons(low_rate)
    assert ValidationReason.GAP_TOO_LARGE in _reasons(tuple(gap_frames))


def test_rule_engine_rejects_no_variation_and_fixed_nonzero_area() -> None:
    timestamps = range(0, 5_000_000_001, 50_000_000)
    unchanged = tuple(
        _frame(np.zeros((48, 64), dtype=np.uint8), timestamp, index)
        for index, timestamp in enumerate(timestamps)
    )
    fixed_nonzero = tuple(
        _frame(np.full((48, 64), 10, dtype=np.uint8), timestamp, index)
        for index, timestamp in enumerate(timestamps)
    )

    assert ValidationReason.NO_VARIATION in _reasons(unchanged)
    assert ValidationReason.FIXED_VALUE_AREA in _reasons(fixed_nonzero)


def test_rule_engine_accepts_sparse_real_empty_board_jitter() -> None:
    """Stable real empty-board output need not vary across most 48x64 cells."""

    frames = list(_healthy_frames())
    for index, frame in enumerate(frames):
        values = np.zeros((48, 64), dtype=np.uint8)
        for row, column in ((0, 1), (3, 9), (11, 17), (19, 25)):
            values[row, column] = index % 2
        frames[index] = _frame(values, frame.host_monotonic_ns, frame.source_index)

    evaluation = evaluate_baseline(
        tuple(frames), _statistics(tuple(frames)), ValidationThresholds()
    )

    assert evaluation.outcome is ValidationOutcome.PASS
    assert ValidationReason.NO_VARIATION not in evaluation.reasons


def test_rule_engine_rejects_saturation_and_persistent_local_anomaly() -> None:
    saturated = list(_healthy_frames())
    for index, frame in enumerate(saturated):
        values = frame.values.copy()
        values[:8, :8] = 255
        saturated[index] = _frame(values, frame.host_monotonic_ns, frame.source_index)
    local_fault = list(_healthy_frames())
    for index, frame in enumerate(local_fault):
        values = frame.values.copy()
        values[12, 17] = 90
        local_fault[index] = _frame(values, frame.host_monotonic_ns, frame.source_index)

    assert ValidationReason.SATURATION in _reasons(tuple(saturated))
    assert ValidationReason.LOCAL_ANOMALY in _reasons(tuple(local_fault))


def test_rule_engine_rejects_temporal_noise_and_drift() -> None:
    noisy = list(_healthy_frames())
    rng = np.random.default_rng(113)
    for index, frame in enumerate(noisy):
        values = rng.integers(0, 9, size=(48, 64), dtype=np.uint8)
        noisy[index] = _frame(values, frame.host_monotonic_ns, frame.source_index)
    drifting = list(_healthy_frames())
    for index, frame in enumerate(drifting):
        drift = min(4, index // 25)
        values = np.clip(frame.values.astype(np.int16) + drift, 0, 255).astype(np.uint8)
        drifting[index] = _frame(values, frame.host_monotonic_ns, frame.source_index)

    assert ValidationReason.NOISE in _reasons(tuple(noisy))
    assert ValidationReason.DRIFT in _reasons(tuple(drifting))


def test_rule_engine_rejects_wrong_shape_or_dtype_as_signal_invalid() -> None:
    bad_shape = _healthy_frames()
    bad = list(bad_shape)
    bad[0] = _frame(np.zeros((32, 32), dtype=np.uint8), 0, 0)

    evaluation = evaluate_baseline(
        tuple(bad),
        _statistics(tuple(bad)),
        ValidationThresholds(),
    )

    assert evaluation.outcome is ValidationOutcome.RETRYABLE_FAIL
    assert evaluation.reasons == (ValidationReason.SIGNAL_INVALID,)
