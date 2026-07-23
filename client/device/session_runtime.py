"""Hardware-only composition from byte transport to validity-gated local sessions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
import time
from typing import Protocol

from client.spool.session_commit import StagedFrameSink, ValidSessionStager

from .acquisition import (
    AcquisitionOutcome,
    AcquisitionResult,
    AcquisitionRunner,
    ConnectionStateMachine,
    LatestFrameMailbox,
)
from .protocol import DaoOneP4864Parser, RawFrame
from .transport import ByteTransport

try:  # avoid making generic acquisition depend on standardization implementation
    from client.hardware_standardization.models import PhysicalArraySession
except ImportError:  # pragma: no cover - only protects isolated transport builds
    PhysicalArraySession = object  # type: ignore[misc,assignment]


class SessionValidity(StrEnum):
    VALID = "VALID"
    INVALID = "INVALID"


@dataclass(frozen=True, slots=True)
class QualityDecision:
    validity: SessionValidity
    reason: str | None = None
    physical_session: PhysicalArraySession | None = None


class HardwareQualityGate(Protocol):
    def evaluate(
        self, *, session_id: str, frames: tuple[RawFrame, ...]
    ) -> QualityDecision: ...


@dataclass(frozen=True, slots=True)
class HardwareSessionResult:
    acquisition: AcquisitionResult
    validity: SessionValidity
    reason: str | None
    committed: bool


class HardwareSessionRuntime:
    """Composition root with no UI, networking, reporting or algorithm dependency."""

    def __init__(
        self,
        *,
        transport: ByteTransport,
        parser: DaoOneP4864Parser,
        connection: ConnectionStateMachine,
        mailbox: LatestFrameMailbox,
        stager: ValidSessionStager,
        quality_gate: HardwareQualityGate,
        maximum_host_gap_ns: int | None = None,
        maximum_idle_read_ns: int | None = None,
        storage_append_timeout_s: float | None = None,
        wall_time_ns: Callable[[], int] = time.time_ns,
    ) -> None:
        self._transport = transport
        self._parser = parser
        self._connection = connection
        self._mailbox = mailbox
        self._stager = stager
        self._quality_gate = quality_gate
        self._maximum_host_gap_ns = maximum_host_gap_ns
        self._maximum_idle_read_ns = maximum_idle_read_ns
        self._storage_append_timeout_s = storage_append_timeout_s
        self._wall_time_ns = wall_time_ns

    def capture(
        self,
        *,
        session_id: str,
        target_frames: int | None = None,
        minimum_duration_ns: int | None = None,
    ) -> HardwareSessionResult:
        self._stager.freeze_versions(self._frozen_runtime_versions())
        acquisition = AcquisitionRunner(
            transport=self._transport,
            parser=self._parser,
            durable_sink=StagedFrameSink(self._stager),
            latest_mailbox=self._mailbox,
            connection=self._connection,
            maximum_host_gap_ns=self._maximum_host_gap_ns,
            maximum_idle_read_ns=self._maximum_idle_read_ns,
            storage_append_timeout_s=self._storage_append_timeout_s,
        ).run(
            session_id=session_id,
            target_frames=target_frames,
            minimum_duration_ns=minimum_duration_ns,
        )
        if acquisition.outcome is not AcquisitionOutcome.COMPLETED:
            return HardwareSessionResult(
                acquisition, SessionValidity.INVALID, acquisition.reason, False
            )
        try:
            decision = self._quality_gate.evaluate(
                session_id=session_id, frames=self._stager.staged_frames()
            )
        except Exception as exc:
            return self._discard_after_acquisition_failure(
                acquisition, reason=f"hardware quality evaluation failed: {type(exc).__name__}"
            )
        decision_value = getattr(decision.validity, "value", decision.validity)
        reason = getattr(decision, "reason", None)
        if reason is None and hasattr(decision, "reasons"):
            reason = "; ".join(getattr(decision, "reasons")) or None
        if decision_value == SessionValidity.INVALID.value:
            self._stager.discard(reason=reason or "hardware quality gate failed")
            return HardwareSessionResult(acquisition, SessionValidity.INVALID, reason, False)
        try:
            physical_session = getattr(decision, "physical_session", None)
            if physical_session is not None:
                self._stager.stage_derived_observation(
                    physical_session,
                    processing_metadata=getattr(decision, "processing_metadata", None),
                )
            self._stager.commit_valid(ended_at_ns=self._wall_time_ns())
        except Exception as exc:
            return self._discard_after_acquisition_failure(
                acquisition, reason=f"valid-session finalization failed: {type(exc).__name__}"
            )
        return HardwareSessionResult(acquisition, SessionValidity.VALID, None, True)

    def _discard_after_acquisition_failure(
        self, acquisition: AcquisitionResult, *, reason: str
    ) -> HardwareSessionResult:
        try:
            self._stager.discard(reason=reason)
        except Exception as cleanup_error:
            reason = f"{reason}; temporary cleanup failed: {type(cleanup_error).__name__}"
        return HardwareSessionResult(acquisition, SessionValidity.INVALID, reason, False)

    def _frozen_runtime_versions(self) -> dict[str, str]:
        versions = {
            "protocol_profile": self._parser.profile.version,
            "maximum_host_gap_ns": str(self._maximum_host_gap_ns),
            "maximum_idle_read_ns": str(self._maximum_idle_read_ns),
            "storage_append_timeout_ms": str(
                None
                if self._storage_append_timeout_s is None
                else round(self._storage_append_timeout_s * 1_000)
            ),
        }
        quality_versions = getattr(
            self._quality_gate, "frozen_configuration_versions", None
        )
        if callable(quality_versions):
            versions.update(quality_versions())
        return versions
