"""Translate the hardware-safe failure DTO into an operator workflow error."""

from __future__ import annotations

from client.device.session_ui import HardwareUiFailure, HardwareUiFailureCode
from client.workflow.models import ClientAction, ClientError


_PRESENTATIONS: dict[HardwareUiFailureCode, tuple[str, str]] = {
    HardwareUiFailureCode.DEVICE_DISCONNECTED: (
        "E-DEV-002",
        "压力设备连接已中断，请重新连接设备后重新检测。",
    ),
    HardwareUiFailureCode.NO_VALID_SIGNAL: (
        "E-ACQ-105",
        "未检测到有效压力信号，请检查压力垫和受试者站位后重新检测。",
    ),
    HardwareUiFailureCode.SENSOR_DATA_UNUSABLE: (
        "E-DEV-109",
        "传感器数据不可用，请检查压力垫后重新检测。",
    ),
    HardwareUiFailureCode.FORCE_CONVERSION_FAILED: (
        "E-DEV-109",
        "压力换算未完成，请检查压力垫后重新检测。",
    ),
    HardwareUiFailureCode.LOCAL_STORAGE_UNAVAILABLE: (
        "E-DAT-102",
        "本地存储空间不可用，请释放空间后重新检测。",
    ),
    HardwareUiFailureCode.LOCAL_FINALIZATION_FAILED: (
        "E-DAT-102",
        "本次检测未能完成本地保存，请联系技术支持。",
    ),
    HardwareUiFailureCode.HARDWARE_PROCESSING_FAILED: (
        "E-INI-006",
        "硬件处理未完成，请联系技术支持。",
    ),
}


def resolve_hardware_ui_failure(failure: HardwareUiFailure) -> ClientError:
    """Return stable copy suitable for the operator UI, never audit detail."""

    code, operator_message = _PRESENTATIONS[failure.code]
    return ClientError(
        code=code,
        operator_message=operator_message,
        action=(
            ClientAction.RETRY_SCREENING
            if failure.retry_allowed
            else ClientAction.CONTACT_SUPPORT
        ),
    )
