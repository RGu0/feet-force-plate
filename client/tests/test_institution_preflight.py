from __future__ import annotations

from client.app.preflight import HardwareLeasePreflight, ProductionPreflightService
from client.spool.state_store import SensitiveBlobCodec, StateStore
from client.startup_validation.models import (
    DeviceValidationRun,
    ValidationOutcome,
    ValidationStatistics,
)
from client.workflow.models import PreflightCheck


class _KeyProvider:
    def get_key(self) -> bytes:
        return b"p" * 32


def _passing_startup_run() -> DeviceValidationRun:
    statistics = ValidationStatistics(
        start_monotonic_ns=1_000_000_000, end_monotonic_ns=6_100_000_000,
        start_wall_time_ns=10_000_000_000, end_wall_time_ns=15_100_000_000,
        start_source_index=0, end_source_index=105, valid_frame_count=106,
        invalid_candidate_count=0, resynchronization_count=0, received_rate_hz=20.588235,
        maximum_host_gap_ns=55_000_000,
    )
    return DeviceValidationRun(
        validation_run_id="validation-pass-1", previous_validation_run_id=None,
        terminal_id="terminal-001", device_ref="hardware-approved-1", attempt_number=1,
        app_version="0.1.0", protocol_version="startup-validation/1",
        data_mode_version="48x64-uint8-column-major/1", rules_version="startup-baseline/2",
        threshold_version="startup-baseline-thresholds/2", started_at_wall_ns=10_000_000_000,
        completed_at_wall_ns=15_100_000_000, outcome=ValidationOutcome.PASS, reason=None,
        error_code=None, diagnostic_id="diagnostic-pass-1", statistics=statistics,
        transition_names=("BOOTSTRAPPING", "WAITING_FOR_EMPTY", "COLLECTING_BASELINE", "PASSED"),
    )


class _Lease:
    def __init__(self, *, permitted: bool = True, raises: bool = False) -> None:
        self.permitted = permitted
        self.raises = raises
        self.acquire_count = 0

    @property
    def allows_new_session(self) -> bool:
        return self.permitted

    def acquire(self):
        self.acquire_count += 1
        if self.raises:
            raise RuntimeError("service unavailable")
        return object()


def _preflight(tmp_path, lease) -> ProductionPreflightService:
    store = StateStore(tmp_path / "state.sqlite3", SensitiveBlobCodec(_KeyProvider()))
    store.record_successful_online(200_000_000_000_000)
    return ProductionPreflightService(
        startup_run=_passing_startup_run(), new_test_gate=store,
        calibration_profile_version="profile/1", calibration_validation="MVP_SCREENING_ESTIMATED_V1",
        now_ns=lambda: 200_000_000_000_000, free_disk_bytes=lambda: 2 * 1024**3,
        estimated_test_bytes=64 * 1024**2, reserve_bytes=512 * 1024**2,
        hardware_lease=HardwareLeasePreflight(lease),
    )


def test_preflight_acquires_a_server_authorized_hardware_lease_before_a_new_session(tmp_path) -> None:
    lease = _Lease()
    summary = _preflight(tmp_path, lease).run_preflight()

    assert summary.ready
    assert lease.acquire_count == 1
    assert summary.checks[-1] == PreflightCheck(
        "hardware_lease", True, operator_message="设备使用授权已取得"
    )


def test_preflight_blocks_a_new_session_when_the_hardware_lease_cannot_be_acquired(tmp_path) -> None:
    summary = _preflight(tmp_path, _Lease(raises=True)).run_preflight()

    assert not summary.ready
    assert summary.first_failure == PreflightCheck(
        "hardware_lease", False, "E-LIC-201",
        "未取得设备使用授权，请确认登录、设备编号和网络后重试",
    )
