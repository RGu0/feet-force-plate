"""Stable, UI-safe hardware session failure results.

This module is deliberately independent of Qt, workflow, networking and the
algorithm contract.  Hardware may retain detailed audit reasons locally, while
the application receives only a stable cause code and an actionable recovery.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class HardwareUiFailureCode(StrEnum):
    DEVICE_DISCONNECTED = "DEVICE_DISCONNECTED"
    NO_VALID_SIGNAL = "NO_VALID_SIGNAL"
    SENSOR_DATA_UNUSABLE = "SENSOR_DATA_UNUSABLE"
    FORCE_CONVERSION_FAILED = "FORCE_CONVERSION_FAILED"
    LOCAL_STORAGE_UNAVAILABLE = "LOCAL_STORAGE_UNAVAILABLE"
    LOCAL_FINALIZATION_FAILED = "LOCAL_FINALIZATION_FAILED"
    HARDWARE_PROCESSING_FAILED = "HARDWARE_PROCESSING_FAILED"


class HardwareRecoveryAction(StrEnum):
    RECONNECT_DEVICE = "RECONNECT_DEVICE"
    CHECK_SENSOR_AND_RETRY = "CHECK_SENSOR_AND_RETRY"
    FREE_LOCAL_STORAGE = "FREE_LOCAL_STORAGE"
    CONTACT_SUPPORT = "CONTACT_SUPPORT"


@dataclass(frozen=True, slots=True)
class HardwareUiFailure:
    """The only hardware-failure payload intended for a software/UI consumer.

    ``operator_message_key`` is a localization key, not a raw exception message.
    Detailed reasons remain in the hardware audit path associated with the session.
    """

    code: HardwareUiFailureCode
    recovery_action: HardwareRecoveryAction
    retry_allowed: bool
    operator_message_key: str


def from_acquisition_reason(reason: str | None) -> HardwareUiFailure:
    """Classify acquisition failures without exposing transport/storage internals."""

    normalized = (reason or "").lower()
    if "transport disconnected" in normalized:
        return _failure(
            HardwareUiFailureCode.DEVICE_DISCONNECTED,
            HardwareRecoveryAction.RECONNECT_DEVICE,
            True,
        )
    if "no valid decoded signal" in normalized:
        return _failure(
            HardwareUiFailureCode.NO_VALID_SIGNAL,
            HardwareRecoveryAction.CHECK_SENSOR_AND_RETRY,
            True,
        )
    if "storage handoff failed" in normalized:
        return _failure(
            HardwareUiFailureCode.LOCAL_STORAGE_UNAVAILABLE,
            HardwareRecoveryAction.FREE_LOCAL_STORAGE,
            True,
        )
    return _failure(
        HardwareUiFailureCode.HARDWARE_PROCESSING_FAILED,
        HardwareRecoveryAction.CONTACT_SUPPORT,
        False,
    )


def from_quality_reasons(
    reasons: tuple[str, ...], *, fallback_reason: str | None = None
) -> HardwareUiFailure:
    """Map hardware quality-gate reason codes to an operator-facing outcome."""

    reason_set = set(reasons)
    if "NO_CAPTURED_FRAMES" in reason_set:
        return _failure(
            HardwareUiFailureCode.NO_VALID_SIGNAL,
            HardwareRecoveryAction.CHECK_SENSOR_AND_RETRY,
            True,
        )
    if "FORCE_CONVERSION_OR_SATURATION_FAILED" in reason_set:
        return _failure(
            HardwareUiFailureCode.FORCE_CONVERSION_FAILED,
            HardwareRecoveryAction.CHECK_SENSOR_AND_RETRY,
            True,
        )
    if reason_set or fallback_reason:
        return _failure(
            HardwareUiFailureCode.SENSOR_DATA_UNUSABLE,
            HardwareRecoveryAction.CHECK_SENSOR_AND_RETRY,
            True,
        )
    return _failure(
        HardwareUiFailureCode.HARDWARE_PROCESSING_FAILED,
        HardwareRecoveryAction.CONTACT_SUPPORT,
        False,
    )


def finalization_failed() -> HardwareUiFailure:
    """Report a safe generic local-finalization problem to the operator."""

    return _failure(
        HardwareUiFailureCode.LOCAL_FINALIZATION_FAILED,
        HardwareRecoveryAction.CONTACT_SUPPORT,
        False,
    )


def processing_failed() -> HardwareUiFailure:
    return _failure(
        HardwareUiFailureCode.HARDWARE_PROCESSING_FAILED,
        HardwareRecoveryAction.CONTACT_SUPPORT,
        False,
    )


def _failure(
    code: HardwareUiFailureCode,
    recovery_action: HardwareRecoveryAction,
    retry_allowed: bool,
) -> HardwareUiFailure:
    return HardwareUiFailure(
        code=code,
        recovery_action=recovery_action,
        retry_allowed=retry_allowed,
        operator_message_key=f"hardware.failure.{code.value.lower()}",
    )
