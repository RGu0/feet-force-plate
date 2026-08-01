from __future__ import annotations

from dataclasses import replace

from PySide6.QtWidgets import QLabel

from client.app.pages import PageId
from client.app.preflight import ProductionPreflightService, build_production_preflight
from client.app.qt_shell import ScreeningWindow
from client.spool.state_store import SensitiveBlobCodec, StateStore
from client.startup_validation.models import (
    DeviceValidationRun,
    ValidationOutcome,
    ValidationReason,
    ValidationStatistics,
)
from client.workflow.models import WorkflowState
from client.workflow.state_machine import ScreeningStep


class _KeyProvider:
    def get_key(self) -> bytes:
        return b"p" * 32


def _passing_startup_run() -> DeviceValidationRun:
    statistics = ValidationStatistics(
        start_monotonic_ns=1_000_000_000,
        end_monotonic_ns=6_100_000_000,
        start_wall_time_ns=10_000_000_000,
        end_wall_time_ns=15_100_000_000,
        start_source_index=0,
        end_source_index=105,
        valid_frame_count=106,
        invalid_candidate_count=0,
        resynchronization_count=0,
        received_rate_hz=20.588235,
        maximum_host_gap_ns=55_000_000,
    )
    return DeviceValidationRun(
        validation_run_id="validation-pass-1",
        previous_validation_run_id=None,
        terminal_id="terminal-001",
        device_ref="hardware-approved-1",
        attempt_number=1,
        app_version="0.1.0",
        protocol_version="startup-validation/1",
        data_mode_version="48x64-uint8-column-major/1",
        rules_version="startup-baseline/2",
        threshold_version="startup-baseline-thresholds/2",
        started_at_wall_ns=10_000_000_000,
        completed_at_wall_ns=15_100_000_000,
        outcome=ValidationOutcome.PASS,
        reason=None,
        error_code=None,
        diagnostic_id="diagnostic-pass-1",
        statistics=statistics,
        transition_names=(
            "BOOTSTRAPPING",
            "WAITING_FOR_EMPTY",
            "COLLECTING_BASELINE",
            "PASSED",
        ),
    )


def test_production_preflight_presents_all_five_passed_checks(qtbot, tmp_path) -> None:
    """Catch P-05 omitting a required gate or hiding it from the operator."""

    now_ns = 200_000_000_000_000
    store = StateStore(
        tmp_path / "state.sqlite3",
        SensitiveBlobCodec(_KeyProvider()),
    )
    store.record_successful_online(now_ns)
    preflight = ProductionPreflightService(
        startup_run=_passing_startup_run(),
        new_test_gate=store,
        calibration_profile_version="do-p4864-voltage-force/mvp-screening-v1-20260722",
        calibration_validation="MVP_SCREENING_ESTIMATED_V1",
        now_ns=lambda: now_ns,
        free_disk_bytes=lambda: 2 * 1024**3,
        estimated_test_bytes=64 * 1024**2,
        reserve_bytes=512 * 1024**2,
    )

    summary = preflight.run_preflight()

    assert summary.ready
    assert [check.key for check in summary.checks] == [
        "device_connected",
        "storage_space",
        "calibration_status",
        "network_gate",
        "zero_load",
    ]
    window = ScreeningWindow()
    qtbot.addWidget(window)
    window.present_state(
        WorkflowState(
            step=ScreeningStep.PREFLIGHT,
            preflight_checks=summary.checks,
            preflight_ready=True,
        )
    )
    page = window.page_widget(PageId.PREFLIGHT)
    assert page.findChild(QLabel, "deviceCheckHint").text() == "启动连接检查已通过"
    assert page.findChild(QLabel, "storageCheckHint").text() == "可用空间满足本次检测"
    assert page.findChild(QLabel, "calibrationCheckHint").text() == "筛查估算标定配置已加载"
    assert page.findChild(QLabel, "syncCheckHint").text() == "联网与待传门槛允许新检测"
    assert page.findChild(QLabel, "zeroLoadCheckHint").text() == "五秒空载检查已通过"
    assert page.findChild(QLabel, "preflightNote").text() == (
        "五项预检已通过，请点击进入站位引导"
    )


def test_production_preflight_allows_the_exact_24_hour_online_boundary(tmp_path) -> None:
    """Catch the client blocking earlier than the approved 24-hour policy."""

    now_ns = 300_000_000_000_000
    store = StateStore(
        tmp_path / "state.sqlite3",
        SensitiveBlobCodec(_KeyProvider()),
    )
    store.record_successful_online(now_ns - 24 * 60 * 60 * 1_000_000_000)
    summary = ProductionPreflightService(
        startup_run=_passing_startup_run(),
        new_test_gate=store,
        calibration_profile_version="do-p4864-voltage-force/mvp-screening-v1-20260722",
        calibration_validation="MVP_SCREENING_ESTIMATED_V1",
        now_ns=lambda: now_ns,
        free_disk_bytes=lambda: 2 * 1024**3,
        estimated_test_bytes=64 * 1024**2,
        reserve_bytes=512 * 1024**2,
    ).run_preflight()

    network = next(check for check in summary.checks if check.key == "network_gate")
    assert network.ready
    assert network.error_code is None


def test_production_preflight_blocks_only_storage_when_capacity_is_insufficient(
    tmp_path,
) -> None:
    """Catch a disk problem being mislabeled as a network outage."""

    now_ns = 400_000_000_000_000
    store = StateStore(
        tmp_path / "state.sqlite3",
        SensitiveBlobCodec(_KeyProvider()),
    )
    store.record_successful_online(now_ns)
    summary = ProductionPreflightService(
        startup_run=_passing_startup_run(),
        new_test_gate=store,
        calibration_profile_version="profile/1",
        calibration_validation="MVP_SCREENING_ESTIMATED_V1",
        now_ns=lambda: now_ns,
        free_disk_bytes=lambda: 575 * 1024**2,
        estimated_test_bytes=64 * 1024**2,
        reserve_bytes=512 * 1024**2,
    ).run_preflight()
    checks = {check.key: check for check in summary.checks}

    assert not checks["storage_space"].ready
    assert checks["storage_space"].error_code == "E-DAT-002"
    assert checks["network_gate"].ready


def test_production_preflight_blocks_unapproved_calibration_configuration(tmp_path) -> None:
    """Catch an unvalidated force configuration being presented as ready."""

    now_ns = 500_000_000_000_000
    store = StateStore(
        tmp_path / "state.sqlite3",
        SensitiveBlobCodec(_KeyProvider()),
    )
    store.record_successful_online(now_ns)
    summary = ProductionPreflightService(
        startup_run=_passing_startup_run(),
        new_test_gate=store,
        calibration_profile_version="unapproved/1",
        calibration_validation="UNVALIDATED",
        now_ns=lambda: now_ns,
        free_disk_bytes=lambda: 2 * 1024**3,
        estimated_test_bytes=64 * 1024**2,
        reserve_bytes=512 * 1024**2,
    ).run_preflight()
    calibration = next(
        check for check in summary.checks if check.key == "calibration_status"
    )

    assert not calibration.ready
    assert calibration.error_code == "E-CAL-001"
    assert calibration.operator_message == "设备标定配置不可用，请联系技术支持"


def test_production_preflight_requires_a_passed_startup_run_for_device_and_zero_load(
    tmp_path,
) -> None:
    """Catch a failed empty-board run being reused as device readiness."""

    now_ns = 600_000_000_000_000
    store = StateStore(
        tmp_path / "state.sqlite3",
        SensitiveBlobCodec(_KeyProvider()),
    )
    store.record_successful_online(now_ns)
    failed_run = replace(
        _passing_startup_run(),
        outcome=ValidationOutcome.RETRYABLE_FAIL,
        reason=ValidationReason.LOAD_NOT_EMPTY,
        error_code="E-DEV-103",
    )
    summary = ProductionPreflightService(
        startup_run=failed_run,
        new_test_gate=store,
        calibration_profile_version="profile/1",
        calibration_validation="MVP_SCREENING_ESTIMATED_V1",
        now_ns=lambda: now_ns,
        free_disk_bytes=lambda: 2 * 1024**3,
        estimated_test_bytes=64 * 1024**2,
        reserve_bytes=512 * 1024**2,
    ).run_preflight()
    checks = {check.key: check for check in summary.checks}

    assert not checks["device_connected"].ready
    assert checks["device_connected"].error_code == "E-DEV-101"
    assert not checks["zero_load"].ready
    assert checks["zero_load"].error_code == "E-DEV-103"


def test_production_builder_uses_the_active_hardware_calibration_profile(tmp_path) -> None:
    """Catch formal composition substituting an invented calibration state."""

    now_ns = 700_000_000_000_000
    store = StateStore(
        tmp_path / "state.sqlite3",
        SensitiveBlobCodec(_KeyProvider()),
    )
    store.record_successful_online(now_ns)

    summary = build_production_preflight(
        startup_run=_passing_startup_run(),
        new_test_gate=store,
        storage_root=tmp_path,
        now_ns=lambda: now_ns,
        free_disk_bytes=lambda: 2 * 1024**3,
    ).run_preflight()
    calibration = next(
        check for check in summary.checks if check.key == "calibration_status"
    )

    assert calibration.ready
    assert calibration.operator_message == "筛查估算标定配置已加载"
