from client.device.session_ui import (
    HardwareRecoveryAction,
    HardwareUiFailureCode,
    finalization_failed,
    from_acquisition_reason,
    from_quality_reasons,
)


def test_transport_disconnect_has_reconnect_guidance() -> None:
    outcome = from_acquisition_reason("transport disconnected: cable removed")

    assert outcome.code is HardwareUiFailureCode.DEVICE_DISCONNECTED
    assert outcome.recovery_action is HardwareRecoveryAction.RECONNECT_DEVICE
    assert outcome.retry_allowed is True
    assert outcome.operator_message_key == "hardware.failure.device_disconnected"


def test_no_valid_signal_has_sensor_retry_guidance() -> None:
    outcome = from_acquisition_reason("no valid decoded signal for five seconds")

    assert outcome.code is HardwareUiFailureCode.NO_VALID_SIGNAL
    assert outcome.recovery_action is HardwareRecoveryAction.CHECK_SENSOR_AND_RETRY
    assert outcome.retry_allowed is True


def test_storage_handoff_has_storage_recovery_guidance() -> None:
    outcome = from_acquisition_reason("storage handoff failed: OSError: no space")

    assert outcome.code is HardwareUiFailureCode.LOCAL_STORAGE_UNAVAILABLE
    assert outcome.recovery_action is HardwareRecoveryAction.FREE_LOCAL_STORAGE
    assert outcome.retry_allowed is True


def test_quality_gate_force_failure_is_not_exposed_as_raw_detail() -> None:
    outcome = from_quality_reasons(("FORCE_CONVERSION_OR_SATURATION_FAILED",))

    assert outcome.code is HardwareUiFailureCode.FORCE_CONVERSION_FAILED
    assert outcome.recovery_action is HardwareRecoveryAction.CHECK_SENSOR_AND_RETRY
    assert "FORCE_CONVERSION_OR_SATURATION_FAILED" not in outcome.operator_message_key


def test_finalization_failure_requires_support_not_raw_exception() -> None:
    outcome = finalization_failed()

    assert outcome.code is HardwareUiFailureCode.LOCAL_FINALIZATION_FAILED
    assert outcome.recovery_action is HardwareRecoveryAction.CONTACT_SUPPORT
    assert outcome.retry_allowed is False
