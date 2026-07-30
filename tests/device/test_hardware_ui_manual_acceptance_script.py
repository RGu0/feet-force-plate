from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from client.device.session_ui import (
    HardwareRecoveryAction,
    HardwareUiFailureCode,
)


SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "run_hardware_ui_manual_acceptance.py"
)


def _script_module():
    spec = spec_from_file_location("hardware_ui_manual_acceptance", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_manual_ui_runner_exposes_only_the_two_recovery_acceptance_scenarios() -> None:
    module = _script_module()

    retryable = module.failure_for("device-disconnected")
    support_only = module.failure_for("local-finalization-failed")

    assert retryable.code is HardwareUiFailureCode.DEVICE_DISCONNECTED
    assert retryable.recovery_action is HardwareRecoveryAction.RECONNECT_DEVICE
    assert retryable.retry_allowed is True
    assert support_only.code is HardwareUiFailureCode.LOCAL_FINALIZATION_FAILED
    assert support_only.recovery_action is HardwareRecoveryAction.CONTACT_SUPPORT
    assert support_only.retry_allowed is False
