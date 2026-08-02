from __future__ import annotations

from collections.abc import Callable

from client.hardware_standardization.runtime import (
    HardwareConnectionUnavailable,
    HardwareRuntime,
    active_hardware_runtime,
)

from .workflow import (
    DeviceBusy,
    DeviceIdentityMismatch,
    DeviceNotFound,
    ValidationConnection,
)


class SerialValidationConnector:
    """Adapt the hardware layer's generic startup connection to the workflow."""

    def __init__(
        self,
        *,
        runtime: HardwareRuntime | None = None,
        connection_factory: Callable[[], object] | None = None,
        expected_hardware_identity: str | None = None,
    ) -> None:
        self._runtime = runtime or active_hardware_runtime()
        self._connection_factory = connection_factory
        self._expected_hardware_identity = expected_hardware_identity

    def connect(self) -> ValidationConnection:
        try:
            if self._connection_factory is None:
                connection = self._runtime.connect_startup(
                    expected_hardware_identity=self._expected_hardware_identity
                )
            else:
                connection = self._connection_factory()
        except HardwareConnectionUnavailable as error:
            if error.code == "BUSY":
                raise DeviceBusy("supported pressure device is unavailable") from error
            if error.code == "IDENTITY_MISMATCH":
                raise DeviceIdentityMismatch(
                    "connected pressure device does not match the active License"
                ) from error
            raise DeviceNotFound("supported pressure device was not found") from error
        except Exception as error:
            raise DeviceNotFound("supported pressure device discovery failed") from error
        if (
            self._expected_hardware_identity is not None
            and connection.hardware_identity != self._expected_hardware_identity
        ):
            connection.transport.close()
            raise DeviceIdentityMismatch(
                "connected pressure device does not match the active License"
            )
        return ValidationConnection(
            device_ref=connection.device_ref,
            transport=connection.transport,
            parser=connection.parser,
            hardware_identity=connection.hardware_identity,
        )
