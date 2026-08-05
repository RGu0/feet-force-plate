"""Production P-05 composition over local startup, storage, and policy evidence."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import shutil
import time
from typing import Protocol

from client.hardware_standardization.runtime import (
    HardwareRuntime,
    active_hardware_runtime,
)
from client.spool.state_store import GateReason, NewTestDecision
from client.startup_validation.models import DeviceValidationRun, ValidationOutcome
from client.workflow.models import PreflightCheck, PreflightSummary


class HardwareLeasePreflightPort(Protocol):
    """The server lease is a precondition for beginning a new live session."""

    def acquire_for_new_session(self) -> PreflightCheck: ...


class HardwareLeasePreflight:
    """Translate the lease lifecycle into one typed, operator-visible P-05 check."""

    def __init__(self, lifecycle) -> None:
        self._lifecycle = lifecycle

    def acquire_for_new_session(self) -> PreflightCheck:
        try:
            self._lifecycle.acquire()
        except Exception:
            return PreflightCheck(
                "hardware_lease", False, "E-LIC-201",
                "未取得设备使用授权，请确认登录、设备编号和网络后重试",
            )
        if not self._lifecycle.allows_new_session:
            return PreflightCheck(
                "hardware_lease", False, "E-LIC-201",
                "设备使用授权不可用，请重新登录后重试",
            )
        return PreflightCheck("hardware_lease", True, operator_message="设备使用授权已取得")


class NewTestGatePort(Protocol):
    def evaluate_new_test(
        self,
        *,
        now_ns: int,
        free_disk_bytes: int,
        estimated_test_bytes: int,
        reserve_bytes: int = 0,
    ) -> NewTestDecision: ...


class ProductionPreflightService:
    """Build the operator P-05 checklist without contacting hardware or cloud."""

    def __init__(
        self,
        *,
        startup_run: DeviceValidationRun,
        new_test_gate: NewTestGatePort,
        calibration_profile_version: str,
        calibration_validation: str,
        now_ns: Callable[[], int],
        free_disk_bytes: Callable[[], int],
        estimated_test_bytes: int,
        reserve_bytes: int,
        hardware_lease: HardwareLeasePreflightPort | None = None,
    ) -> None:
        if estimated_test_bytes <= 0 or reserve_bytes < 0:
            raise ValueError("preflight storage thresholds are invalid")
        self._startup_run = startup_run
        self._new_test_gate = new_test_gate
        self._calibration_profile_version = calibration_profile_version.strip()
        self._calibration_validation = calibration_validation.strip()
        self._now_ns = now_ns
        self._free_disk_bytes = free_disk_bytes
        self._estimated_test_bytes = estimated_test_bytes
        self._reserve_bytes = reserve_bytes
        self._hardware_lease = hardware_lease

    def run_preflight(self) -> PreflightSummary:
        startup_ready = (
            self._startup_run.outcome is ValidationOutcome.PASS
            and self._startup_run.statistics is not None
        )
        decision = self._new_test_gate.evaluate_new_test(
            now_ns=self._now_ns(),
            free_disk_bytes=self._free_disk_bytes(),
            estimated_test_bytes=self._estimated_test_bytes,
            reserve_bytes=self._reserve_bytes,
        )
        storage_ready = GateReason.INSUFFICIENT_DISK not in decision.reasons
        network_reasons = tuple(
            reason
            for reason in decision.reasons
            if reason is not GateReason.INSUFFICIENT_DISK
        )
        calibration_ready = bool(self._calibration_profile_version) and (
            self._calibration_validation == "VALIDATED"
            or self._calibration_validation.startswith("MVP_SCREENING_ESTIMATED")
        )
        checks = [
                PreflightCheck(
                    "device_connected",
                    startup_ready,
                    error_code=None if startup_ready else "E-DEV-101",
                    operator_message=(
                        "启动连接检查已通过"
                        if startup_ready
                        else "设备启动检查未通过，请重新启动应用"
                    ),
                ),
                PreflightCheck(
                    "storage_space",
                    storage_ready,
                    error_code=None if storage_ready else "E-DAT-002",
                    operator_message=(
                        "可用空间满足本次检测"
                        if storage_ready
                        else "本机存储空间不足，请清理后重新检查"
                    ),
                ),
                PreflightCheck(
                    "calibration_status",
                    calibration_ready,
                    error_code=None if calibration_ready else "E-CAL-001",
                    operator_message=(
                        "筛查估算标定配置已加载"
                        if calibration_ready
                        else "设备标定配置不可用，请联系技术支持"
                    ),
                ),
                PreflightCheck(
                    "network_gate",
                    not network_reasons,
                    error_code=None if not network_reasons else "E-NET-001",
                    operator_message=(
                        "联网与待传门槛允许新检测"
                        if not network_reasons
                        else "请先联网同步待传数据，再重新检查"
                    ),
                ),
                PreflightCheck(
                    "zero_load",
                    startup_ready,
                    error_code=None if startup_ready else "E-DEV-103",
                    operator_message=(
                        "五秒空载检查已通过"
                        if startup_ready
                        else "设备空载检查未通过，请清空设备并重新启动"
                    ),
                ),
        ]
        if self._hardware_lease is not None:
            checks.append(self._hardware_lease.acquire_for_new_session())
        return PreflightSummary(tuple(checks))


def build_production_preflight(
    *,
    startup_run: DeviceValidationRun,
    new_test_gate: NewTestGatePort,
    storage_root: Path,
    hardware: HardwareRuntime | None = None,
    now_ns: Callable[[], int] = time.time_ns,
    free_disk_bytes: Callable[[], int] | None = None,
    estimated_test_bytes: int = 64 * 1024**2,
    reserve_bytes: int = 512 * 1024**2,
    hardware_lease: HardwareLeasePreflightPort | None = None,
) -> ProductionPreflightService:
    """Compose P-05 from the active device specification and local state store."""

    resolved_hardware = hardware or active_hardware_runtime()
    calibration = resolved_hardware.calibration_metadata
    resolved_free_disk_bytes = free_disk_bytes or (
        lambda: shutil.disk_usage(storage_root).free
    )
    return ProductionPreflightService(
        startup_run=startup_run,
        new_test_gate=new_test_gate,
        calibration_profile_version=calibration.profile_version,
        calibration_validation=calibration.validation,
        now_ns=now_ns,
        free_disk_bytes=resolved_free_disk_bytes,
        estimated_test_bytes=estimated_test_bytes,
        reserve_bytes=reserve_bytes,
        hardware_lease=hardware_lease,
    )
