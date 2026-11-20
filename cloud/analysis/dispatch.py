"""Force-plate analysis handler for foundation's registry-driven dispatch (RAY-1006).

Foundation's payload schema registry binds ``raw-segment/1`` to the analyzer
name ``ffp.force-plate-analysis`` (``FORCE_PLATE_ANALYZER``), and its
``IngestedEventDispatcher`` calls the handler registered under that name for
each ``session.ingested.v1`` event.  Which schemas are analyzed is therefore
decided by the registry, not by schema-name checks in the orchestrators.

The handler feeds the legacy raw-array pipeline (``AnalysisOrchestrator``),
per the RAY-1006 scope registration.  The envelope carries the event, tenant
and correlation identifiers and the payload carries the session, manifest
digest and payload schema; the calibration and protocol-profile versions the
orchestrator keys its runs on are the session's registered versions, read
through :class:`SessionVersionsReader`.  The physical pipeline
(``PhysicalAnalysisOrchestrator``) is not reachable from here: it needs a
``CompleteSessionEvent`` that ``session.ingested.v1`` cannot supply.

This module does not read the outbox or run a worker; that is the consumer's
concern and outside RAY-1006.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from cloud.analysis.models import AnalysisRun, SessionIngestedEvent
from cloud.analysis.orchestrator import AnalysisOrchestrator
from techflex_cloud_foundation import (
    FORCE_PLATE_ANALYZER,
    RAW_SEGMENT_SCHEMA,
    IngestedEventDispatcher,
    PayloadSchemaRegistry,
    default_payload_schema_registry,
)

#: The only payload schema the force-plate handler analyzes.
FORCE_PLATE_PAYLOAD_SCHEMA = RAW_SEGMENT_SCHEMA.schema_id


class ForcePlateEvent(Protocol):
    """The ``session.ingested.v1`` envelope fields the handler reads.

    ``techflex_cloud_foundation.contracts.events.EventEnvelope`` qualifies.
    """

    @property
    def event_id(self) -> Any: ...

    @property
    def event_type(self) -> str: ...

    @property
    def tenant_id(self) -> Any: ...

    @property
    def aggregate_id(self) -> Any: ...

    @property
    def aggregate_version(self) -> int: ...

    @property
    def correlation_id(self) -> Any: ...

    @property
    def payload(self) -> Mapping[str, Any]: ...


@dataclass(frozen=True, slots=True)
class RegisteredSessionVersions:
    """The session's registered calibration and protocol-profile versions."""

    calibration_version: str
    protocol_profile_version: str


class SessionVersionsReader(Protocol):
    def versions(self, tenant_id: str, session_id: str) -> RegisteredSessionVersions: ...


class UnsupportedForcePlateEvent(ValueError):
    """The event cannot be analyzed by the legacy force-plate pipeline."""


def _required_text(payload: Mapping[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value:
        raise UnsupportedForcePlateEvent(f"session.ingested.v1 payload has no {field}")
    return value


def _canonical_uuid(value: object, field: str) -> str:
    try:
        return str(value if isinstance(value, UUID) else UUID(str(value)))
    except ValueError:
        raise UnsupportedForcePlateEvent(
            f"session.ingested.v1 {field} is not a UUID"
        ) from None


class ForcePlateAnalysisHandler:
    """Map a ``session.ingested.v1`` envelope onto ``AnalysisOrchestrator``."""

    def __init__(
        self,
        *,
        orchestrator: AnalysisOrchestrator,
        versions: SessionVersionsReader,
    ) -> None:
        self.orchestrator = orchestrator
        self.versions = versions

    def __call__(self, event: ForcePlateEvent) -> AnalysisRun:
        payload = event.payload
        schema = payload.get("payload_schema_version")
        if schema != FORCE_PLATE_PAYLOAD_SCHEMA:
            # The registry only binds raw-segment/1 here; anything else reaching
            # this handler (for example a derived estimated-force-session
            # document) belongs to another pipeline and is refused before any
            # run is reserved.
            raise UnsupportedForcePlateEvent(
                f"force-plate analysis accepts only {FORCE_PLATE_PAYLOAD_SCHEMA}, "
                f"got {schema!r}"
            )
        session_id = _canonical_uuid(_required_text(payload, "session_id"), "session_id")
        manifest_sha256 = _required_text(payload, "manifest_sha256")
        if _canonical_uuid(event.aggregate_id, "aggregate_id") != session_id:
            raise UnsupportedForcePlateEvent(
                "session.ingested.v1 aggregate_id does not match payload session_id"
            )
        tenant_id = str(event.tenant_id)
        event_id = str(event.event_id)
        registered = self.versions.versions(tenant_id, session_id)
        if not registered.calibration_version or not registered.protocol_profile_version:
            raise UnsupportedForcePlateEvent(
                "session has no registered calibration or protocol-profile version"
            )
        # Ingestion does not set a correlation id on session.ingested.v1; the
        # event id then starts the analysis correlation chain.
        correlation_id = (
            str(event.correlation_id) if event.correlation_id is not None else event_id
        )
        return self.orchestrator.handle(
            SessionIngestedEvent(
                event_id=event_id,
                event_type=event.event_type,
                tenant_id=tenant_id,
                session_id=session_id,
                manifest_sha256=manifest_sha256,
                payload_schema_version=schema,
                protocol_profile_version=registered.protocol_profile_version,
                calibration_version=registered.calibration_version,
                correlation_id=correlation_id,
                aggregate_version=event.aggregate_version,
            )
        )


def build_force_plate_dispatcher(
    handler: ForcePlateAnalysisHandler,
    registry: PayloadSchemaRegistry | None = None,
) -> IngestedEventDispatcher[Any, AnalysisRun]:
    """Register ``handler`` under ``FORCE_PLATE_ANALYZER`` with foundation's dispatcher.

    Construction fails (``AnalyzerHandlerMissing`` / ``AnalyzerHandlerUnbound``)
    when the registry's bindings and the handlers do not match.
    """

    return IngestedEventDispatcher(
        registry if registry is not None else default_payload_schema_registry(),
        {FORCE_PLATE_ANALYZER: handler},
    )
