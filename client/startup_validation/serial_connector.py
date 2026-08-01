from __future__ import annotations

from collections.abc import Callable

from client.hardware_standardization.runtime import (
    HardwareConnectionUnavailable,
    HardwareRuntime,
    active_hardware_runtime,
)

from .workflow import DeviceBusy, DeviceNotFound, ValidationConnection


class SerialValidationConnector:
    """Adapt the hardware layer's generic startup connection to the workflow."""

    def __init__(
        self,
        *,
        runtime: HardwareRuntime | None = None,
        connection_factory: Callable[[], object] | None = None,
    ) -> None:
        self._runtime = runtime or active_hardware_runtime()
        self._connection_factory = connection_factory or self._runtime.connect_startup

    def connect(self) -> ValidationConnection:
        try:
            connection = self._connection_factory()
        except HardwareConnectionUnavailable as error:
            if error.code == "BUSY":
                raise DeviceBusy("supported pressure device is unavailable") from error
            raise DeviceNotFound("supported pressure device was not found") from error
        except Exception as error:
            raise DeviceNotFound("supported pressure device discovery failed") from error
        return ValidationConnection(
            device_ref=connection.device_ref,
            transport=connection.transport,
            parser=connection.parser,
            hardware_identity=connection.hardware_identity,
        )
