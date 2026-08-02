"""Hardware-owned composition for the currently supported physical device.

Upper layers receive generic geometry and decoded-frame contracts from this
facade.  Selecting DO-P4864, opening CH340, configuring serial 8N1 and
constructing its parser remain inside the hardware layer.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from collections.abc import Callable, Sequence
from typing import Any

import numpy as np

from client.device.protocol import DaoOneP4864Parser, ProtocolProfile, RawFrame
from client.device.acquisition import LatestFrameMailbox
from client.device.serial_transport import (
    PortAvailability,
    SerialByteTransport,
    SerialPortCandidate,
    enumerate_ch340_ports,
    stable_hardware_identity,
)
from client.device.transport import ByteTransport

from .do_p4864 import DoP4864StandardizationAdapter
from .live_processing import DoP4864LiveFrameStandardizer, DoP4864LiveProcessingProfile
from .ports import HardwareDisplayGeometry


class HardwareConnectionUnavailable(RuntimeError):
    """The selected hardware cannot provide a startup data source."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class HardwareStartupConnection:
    """Generic startup connection bundle, produced only by the hardware layer."""

    device_ref: str
    transport: ByteTransport
    parser: Any
    hardware_identity: str | None


@dataclass(frozen=True, slots=True)
class HardwareStartupMetadata:
    """Version metadata safe for workflow/audit consumers."""

    data_mode_version: str
    rules_version: str
    threshold_version: str


@dataclass(frozen=True, slots=True)
class HardwareCalibrationMetadata:
    """Public calibration identifiers without exposing the concrete adapter."""

    profile_version: str
    validation: str


class HardwareRuntime:
    """Single implementation-selection point for the active hardware profile."""

    def __init__(
        self,
        adapter: DoP4864StandardizationAdapter | None = None,
        *,
        enumerate_ports: Callable[..., Sequence[SerialPortCandidate]] = enumerate_ch340_ports,
        transport_open: Callable[..., ByteTransport] = SerialByteTransport.open,
    ) -> None:
        self._adapter = adapter or DoP4864StandardizationAdapter.observed_compact_8bit()
        self._enumerate_ports = enumerate_ports
        self._transport_open = transport_open

    @property
    def display_geometry(self) -> HardwareDisplayGeometry:
        specification = self._adapter.specification
        return HardwareDisplayGeometry(
            rows=specification.rows,
            columns=specification.columns,
            width_mm=specification.physical_region_width_mm,
            height_mm=specification.physical_region_height_mm,
            maximum_refresh_hz=specification.observed_frame_rate_hz,
        )

    @property
    def specification_id(self) -> str:
        return self._adapter.specification.specification_id

    @property
    def startup_metadata(self) -> HardwareStartupMetadata:
        specification = self._adapter.specification
        validation = specification.startup_validation
        return HardwareStartupMetadata(
            data_mode_version=specification.data_mode_version,
            rules_version=validation.rules_version,
            threshold_version=validation.threshold_version,
        )

    @property
    def calibration_metadata(self) -> HardwareCalibrationMetadata:
        specification = self._adapter.specification
        return HardwareCalibrationMetadata(
            profile_version=specification.force_calibration_profile_version,
            validation=specification.force_validation,
        )

    def make_validation_thresholds(self):
        """Build startup policy from the selected hardware specification."""

        from client.startup_validation.rules import ValidationThresholds

        return ValidationThresholds.from_device_specification(self._adapter.specification)

    def make_live_standardizer(
        self, profile: DoP4864LiveProcessingProfile
    ) -> DoP4864LiveFrameStandardizer:
        return DoP4864LiveFrameStandardizer(profile, adapter=self._adapter)

    def make_fixture_frame(
        self,
        values: np.ndarray,
        *,
        source_index: int,
        host_monotonic_ns: int,
        quality_flags: frozenset[str],
    ) -> RawFrame:
        """Create a decoded fixture observation without exposing its concrete type."""

        matrix = np.asarray(values).copy()
        if matrix.shape != self._adapter.specification.matrix_shape:
            raise ValueError("fixture matrix does not match selected hardware geometry")
        matrix.setflags(write=False)
        return RawFrame(
            values=matrix,
            host_monotonic_ns=host_monotonic_ns,
            host_wall_time_ns=host_monotonic_ns,
            source_index=source_index,
            device_frame_seq=None,
            device_timestamp_ns=None,
            quality_flags=quality_flags,
        )

    def make_latest_frame_mailbox(self) -> Any:
        """Create the hardware-owned latest-frame port for a UI projection."""

        return LatestFrameMailbox()

    def connect_startup(
        self, *, expected_hardware_identity: str | None = None
    ) -> HardwareStartupConnection:
        specification = self._adapter.specification
        serial_options = {
            "baud_rate": specification.serial_baud_rate,
            "data_bits": specification.serial_data_bits,
            "parity": specification.serial_parity,
            "stop_bits": specification.serial_stop_bits,
        }
        try:
            candidates = tuple(self._enumerate_ports(**serial_options))
        except Exception as error:
            raise HardwareConnectionUnavailable("NOT_FOUND", "device discovery failed") from error
        available = tuple(
            candidate
            for candidate in candidates
            if candidate.availability is PortAvailability.AVAILABLE
        )
        if not available:
            code = "BUSY" if candidates else "NOT_FOUND"
            raise HardwareConnectionUnavailable(code, "supported pressure device is unavailable")
        candidate = available[0]
        if expected_hardware_identity is not None:
            matching = tuple(
                item
                for item in available
                if stable_hardware_identity(item) == expected_hardware_identity
            )
            if len(matching) != 1:
                raise HardwareConnectionUnavailable(
                    "IDENTITY_MISMATCH",
                    "connected pressure device does not match the active License",
                )
            candidate = matching[0]
        try:
            transport = self._transport_open(candidate.device, **serial_options)
        except Exception as error:
            raise HardwareConnectionUnavailable("BUSY", "supported pressure device could not be opened") from error
        profile = ProtocolProfile.observed_compact_8bit(
            version=self._adapter.specification.source_schema_version
        )
        return HardwareStartupConnection(
            device_ref=_opaque_device_ref(candidate.device),
            transport=transport,
            parser=DaoOneP4864Parser(profile),
            hardware_identity=stable_hardware_identity(candidate),
        )


def active_hardware_runtime() -> HardwareRuntime:
    """Return the active production hardware composition without exposing it."""

    return HardwareRuntime()


def _opaque_device_ref(device: str) -> str:
    digest = hashlib.sha256(device.encode("utf-8")).hexdigest()[:20]
    return f"hardware-{digest}"
