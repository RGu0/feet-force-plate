"""RAY-1006: force-plate analysis is reached through foundation's registry dispatch."""

import unittest
from datetime import UTC, datetime
from uuid import UUID, uuid4

from cloud.analysis.dispatch import (
    FORCE_PLATE_PAYLOAD_SCHEMA,
    ForcePlateAnalysisHandler,
    RegisteredSessionVersions,
    UnsupportedForcePlateEvent,
    build_force_plate_dispatcher,
)
from cloud.analysis.models import AnalysisRunStatus, RawSession
from cloud.analysis.orchestrator import InMemoryAnalysisRepository
from techflex_cloud_foundation import (
    FORCE_PLATE_ANALYZER,
    DispatchKind,
    PayloadSchemaRegistry,
    RAW_SEGMENT_SCHEMA,
    default_payload_schema_registry,
)
from techflex_cloud_foundation.analysis_dispatch import (
    AnalyzerHandlerUnbound,
    UndispatchableEvent,
)
from techflex_cloud_foundation.contracts.events import EventEnvelope
from techflex_cloud_foundation.server.session_hold.service import SessionHeld
from tests.cloud.analysis.test_orchestrator import (
    Loader,
    MutableHolds,
    context,
    frame,
    orchestrator,
)

TENANT = UUID("00000000-0000-4000-8000-00000000000a")
SESSION = UUID("00000000-0000-4000-8000-0000000000a1")


class Versions:
    def __init__(
        self,
        registered: RegisteredSessionVersions | None = None,
    ) -> None:
        self.registered = registered or RegisteredSessionVersions(
            calibration_version="calibration/1",
            protocol_profile_version="do-p4864/1",
        )
        self.calls: list[tuple[str, str]] = []

    def versions(self, tenant_id: str, session_id: str) -> RegisteredSessionVersions:
        self.calls.append((tenant_id, session_id))
        return self.registered


def envelope(
    *,
    schema: str | None = FORCE_PLATE_PAYLOAD_SCHEMA,
    session_id: UUID = SESSION,
    aggregate_id: UUID | None = None,
    correlation_id: UUID | None = None,
    event_id: UUID | None = None,
    payload_overrides: dict[str, object] | None = None,
) -> EventEnvelope:
    payload: dict[str, object] = {
        "session_id": str(session_id),
        "manifest_sha256": "a" * 64,
        "segment_count": 3,
    }
    if schema is not None:
        payload["payload_schema_version"] = schema
    payload.update(payload_overrides or {})
    return EventEnvelope(
        event_id=event_id or uuid4(),
        event_type="session.ingested.v1",
        occurred_at=datetime(2026, 11, 20, tzinfo=UTC),
        producer="ingestion",
        tenant_id=TENANT,
        aggregate_type="screening_session",
        aggregate_id=aggregate_id or session_id,
        aggregate_version=2,
        correlation_id=correlation_id,
        payload=payload,
    )


class ForcePlateDispatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = InMemoryAnalysisRepository()
        self.loader = Loader(
            RawSession(
                context=context(tenant_id=str(TENANT), session_id=str(SESSION)),
                frames=(frame(),),
            )
        )
        self.holds = MutableHolds()
        self.versions = Versions()
        self.handler = ForcePlateAnalysisHandler(
            orchestrator=orchestrator(
                repository=self.repository, loader=self.loader, holds=self.holds
            ),
            versions=self.versions,
        )
        self.dispatcher = build_force_plate_dispatcher(self.handler)

    def test_default_registry_binds_raw_segment_to_the_force_plate_handler(self) -> None:
        self.assertEqual(FORCE_PLATE_PAYLOAD_SCHEMA, "raw-segment/1")
        self.assertEqual(self.dispatcher.analyzer_for("raw-segment/1"), FORCE_PLATE_ANALYZER)
        self.assertEqual(FORCE_PLATE_ANALYZER, "ffp.force-plate-analysis")

    def test_raw_segment_event_runs_the_legacy_orchestrator(self) -> None:
        event = envelope()

        outcome = self.dispatcher.dispatch(event)

        self.assertEqual(outcome.kind, DispatchKind.ANALYZED)
        self.assertEqual(outcome.analyzer, FORCE_PLATE_ANALYZER)
        run = outcome.result
        assert run is not None
        self.assertEqual(run.status, AnalysisRunStatus.SUCCEEDED)
        self.assertEqual(run.source_event_id, str(event.event_id))
        self.assertEqual(run.correlation_id, str(event.event_id))
        self.assertEqual(run.key.tenant_id, str(TENANT))
        self.assertEqual(run.key.session_id, str(SESSION))
        self.assertEqual(run.key.payload_schema_version, "raw-segment/1")
        self.assertEqual(run.key.calibration_version, "calibration/1")
        self.assertEqual(run.key.protocol_profile_version, "do-p4864/1")
        self.assertEqual(run.key.input_manifest_sha256, "a" * 64)
        self.assertEqual(self.versions.calls, [(str(TENANT), str(SESSION))])
        self.assertEqual(self.loader.calls, 1)
        self.assertEqual(self.repository.count(), 1)

    def test_envelope_correlation_id_is_kept(self) -> None:
        correlation = uuid4()

        run = self.dispatcher.dispatch(envelope(correlation_id=correlation)).result

        assert run is not None
        self.assertEqual(run.correlation_id, str(correlation))

    def test_redelivery_returns_the_same_run(self) -> None:
        first = self.dispatcher.dispatch(envelope()).result
        second = self.dispatcher.dispatch(envelope()).result

        self.assertEqual(first, second)
        self.assertEqual(self.repository.count(), 1)
        self.assertEqual(self.loader.calls, 1)

    def test_unbound_archive_schemas_are_ingest_only(self) -> None:
        for schema in ("insole-session-archive/1", "gait-session-archive/1"):
            with self.subTest(schema=schema):
                outcome = self.dispatcher.dispatch(envelope(schema=schema))
                self.assertEqual(outcome.kind, DispatchKind.INGEST_ONLY)
                self.assertIsNone(outcome.result)
        self.assertEqual(self.versions.calls, [])
        self.assertEqual(self.repository.count(), 0)

    def test_handler_refuses_estimated_force_sessions_before_reserving_a_run(self) -> None:
        # Moved from test_orchestrator: the legacy pipeline's former
        # startswith("estimated-force-session/") rejection is now the handler's
        # raw-segment/1 guard.
        with self.assertRaisesRegex(UnsupportedForcePlateEvent, "raw-segment/1"):
            self.handler(envelope(schema="estimated-force-session/1.1"))

        self.assertEqual(self.versions.calls, [])
        self.assertEqual(self.loader.calls, 0)
        self.assertEqual(self.repository.count(), 0)

    def test_handler_refuses_a_schema_bound_to_it_other_than_raw_segment(self) -> None:
        registry = default_payload_schema_registry()
        registry.bind_analyzer("insole-session-archive/1", FORCE_PLATE_ANALYZER)
        dispatcher = build_force_plate_dispatcher(self.handler, registry)

        with self.assertRaises(UnsupportedForcePlateEvent):
            dispatcher.dispatch(envelope(schema="insole-session-archive/1"))
        self.assertEqual(self.repository.count(), 0)

    def test_payload_without_session_or_manifest_is_refused(self) -> None:
        for field in ("session_id", "manifest_sha256"):
            with self.subTest(field=field):
                with self.assertRaisesRegex(UnsupportedForcePlateEvent, field):
                    self.dispatcher.dispatch(envelope(payload_overrides={field: ""}))
        self.assertEqual(self.repository.count(), 0)

    def test_aggregate_and_payload_session_must_match(self) -> None:
        with self.assertRaisesRegex(UnsupportedForcePlateEvent, "aggregate_id"):
            self.dispatcher.dispatch(envelope(aggregate_id=uuid4()))
        self.assertEqual(self.repository.count(), 0)

    def test_session_ids_are_compared_as_uuids(self) -> None:
        run = self.dispatcher.dispatch(
            envelope(payload_overrides={"session_id": str(SESSION).upper()})
        ).result

        assert run is not None
        self.assertEqual(run.key.session_id, str(SESSION))
        with self.assertRaisesRegex(UnsupportedForcePlateEvent, "not a UUID"):
            self.dispatcher.dispatch(envelope(payload_overrides={"session_id": "session-a"}))

    def test_unregistered_schema_is_undispatchable(self) -> None:
        with self.assertRaises(UndispatchableEvent):
            self.dispatcher.dispatch(envelope(schema="estimated-force-session/1.1"))
        self.assertEqual(self.versions.calls, [])
        self.assertEqual(self.repository.count(), 0)

    def test_missing_registered_versions_are_refused(self) -> None:
        handler = ForcePlateAnalysisHandler(
            orchestrator=orchestrator(repository=self.repository),
            versions=Versions(RegisteredSessionVersions("", "do-p4864/1")),
        )

        with self.assertRaisesRegex(UnsupportedForcePlateEvent, "registered"):
            build_force_plate_dispatcher(handler).dispatch(envelope())
        self.assertEqual(self.repository.count(), 0)

    def test_session_hold_propagates_unchanged_through_the_dispatcher(self) -> None:
        self.holds.held.add((str(TENANT), str(SESSION)))

        with self.assertRaises(SessionHeld):
            self.dispatcher.dispatch(envelope())
        self.assertEqual(self.repository.count(), 0)

    def test_registry_without_the_binding_refuses_to_build(self) -> None:
        registry = PayloadSchemaRegistry()
        registry.register(RAW_SEGMENT_SCHEMA)

        with self.assertRaises(AnalyzerHandlerUnbound):
            build_force_plate_dispatcher(self.handler, registry)


if __name__ == "__main__":
    unittest.main()
