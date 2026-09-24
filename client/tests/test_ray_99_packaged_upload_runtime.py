from __future__ import annotations

import logging
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest

from client.app.session_lock import SessionLockController
from client.sync import runtime as upload_runtime_module
from client.sync.runtime import PackagedUploadRuntime, build_packaged_upload_runtime


def test_upload_runtime_recovers_promoted_files_then_sqlite_before_scheduler(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Catch a restart that races upload recovery, duplicates workers, or closes shared SQLite."""

    order: list[str] = []

    class _PhysicalStore:
        def recover_interrupted_state(self, *, recovered_at_ns: int) -> None:
            assert recovered_at_ns > 0
            order.append("recover_interrupted_state")

        def close(self) -> None:
            order.append("physical_store.close")

    class _UploadScheduler:
        def start(self) -> None:
            order.append("upload_scheduler.start")

        def stop(self) -> None:
            order.append("upload_scheduler.stop")

    class _HttpClient:
        def close(self) -> None:
            order.append("http.close")

    physical_store = _PhysicalStore()
    key_provider = object()
    spool_root = tmp_path / "spool"

    def recover_promoted(root, store, keys) -> int:
        assert root == spool_root
        assert store is physical_store
        assert keys is key_provider
        order.append("recover_promoted_sessions")
        return 1

    monkeypatch.setattr(
        upload_runtime_module.ValidSessionStager,
        "recover_promoted_sessions",
        recover_promoted,
    )

    runtime = PackagedUploadRuntime(
        spool_root=spool_root,
        key_provider=key_provider,
        physical_store=physical_store,
        upload_scheduler=_UploadScheduler(),
        http_client=_HttpClient(),
    )

    runtime.start()
    runtime.start()
    lock = SessionLockController(lambda _password: True)
    lock.lock_now()

    assert lock.state.value == "LOCKED"
    assert "upload_scheduler.stop" not in order

    runtime.close()
    runtime.close()

    assert order[:3] == [
        "recover_promoted_sessions",
        "recover_interrupted_state",
        "upload_scheduler.start",
    ]
    assert order.count("upload_scheduler.start") == 1
    assert order.count("upload_scheduler.stop") == 1
    assert order.count("http.close") == 1
    assert "physical_store.close" not in order


def test_factory_scheduler_recovers_escaped_lease_and_keeps_polling(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Removing escaped-lease recovery, daemon polling, or single-start must fail."""

    first_cycle = threading.Event()
    second_cycle = threading.Event()
    scheduler_threads: set[int] = set()
    delegated_access: list[object] = []
    order: list[str] = []
    queue_roots: list[Path] = []

    class _PhysicalStore:
        def __init__(self) -> None:
            self.lease_count = 0

        def recover_interrupted_state(self, *, recovered_at_ns: int) -> None:
            assert recovered_at_ns > 0
            order.append("recover_interrupted_state")

        def lease_sync_handoff(self, *, now_ns: int):
            assert now_ns > 0
            self.lease_count += 1
            if self.lease_count == 1:
                return SimpleNamespace(session_id="leased-session")
            return None

        def mark_sync_handoff_blocked(self, session_id: str, *, error_code: str) -> None:
            order.append(f"blocked:{session_id}:{error_code}")

    class _HttpClient:
        def __init__(self, *_args, **_kwargs) -> None:
            order.append("http.open")

        def close(self) -> None:
            order.append("http.close")

    class _EventSignallingQueue:
        def __init__(self, store, repository_root, *_args) -> None:
            self.store = store
            queue_roots.append(Path(repository_root))
            self.calls = 0

        def upload_next(self, access_runtime) -> None:
            delegated_access.append(access_runtime)
            scheduler_threads.add(threading.get_ident())
            assert threading.current_thread().daemon is True
            self.calls += 1
            if self.calls == 1:
                self.store.lease_sync_handoff(now_ns=1)
                first_cycle.set()
                raise RuntimeError("credential-shaped-secret-must-not-be-logged")
            second_cycle.set()

    monkeypatch.setattr(upload_runtime_module, "HttpIngestionClient", _HttpClient)
    monkeypatch.setattr(
        upload_runtime_module, "PersistentUploadQueue", _EventSignallingQueue
    )
    physical_store = _PhysicalStore()
    access_runtime = object()
    runtime = build_packaged_upload_runtime(
        tmp_path,
        SimpleNamespace(base_url="https://upload.invalid", verify=True),
        SimpleNamespace(client_installation_id="c03732ad-c781-4364-9d3a-c3ce3ea8488c"),
        access_runtime,
        object(),
        object(),
        physical_store,
    )

    with caplog.at_level(logging.ERROR, logger=upload_runtime_module.__name__):
        runtime.start()
        runtime.start()
        assert first_cycle.wait(timeout=1.0)
        assert second_cycle.wait(timeout=1.0)
        runtime.close()

    assert order.count("recover_interrupted_state") == 1
    assert order.count("blocked:leased-session:E-SYN-500") == 1
    assert len(scheduler_threads) == 1
    assert delegated_access and all(item is access_runtime for item in delegated_access)
    assert queue_roots == [tmp_path / "spool"]
    assert (queue_roots[0] / "sessions") != (tmp_path / "sessions")
    assert "E-SYN-500" in caplog.text
    assert "credential-shaped-secret-must-not-be-logged" not in caplog.text
    assert order[-1] == "http.close"


def test_factory_closes_http_if_queue_construction_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A queue-construction exception must not leak the already-open HTTP client."""

    order: list[str] = []

    class _HttpClient:
        def __init__(self, *_args, **_kwargs) -> None:
            order.append("http.open")

        def close(self) -> None:
            order.append("http.close")

    class _BrokenQueue:
        def __init__(self, *_args) -> None:
            raise RuntimeError("queue construction failed")

    monkeypatch.setattr(upload_runtime_module, "HttpIngestionClient", _HttpClient)
    monkeypatch.setattr(upload_runtime_module, "PersistentUploadQueue", _BrokenQueue)

    with pytest.raises(RuntimeError, match="queue construction failed"):
        build_packaged_upload_runtime(
            tmp_path,
            SimpleNamespace(base_url="https://upload.invalid", verify=True),
            SimpleNamespace(
                client_installation_id="c03732ad-c781-4364-9d3a-c3ce3ea8488c"
            ),
            object(),
            object(),
            object(),
            object(),
        )

    assert order == ["http.open", "http.close"]


def test_packaged_empty_grant_pool_blocks_capture_but_upload_and_history_work(
    monkeypatch: pytest.MonkeyPatch, qtbot,
) -> None:
    """Exercise both packaged roots with real encrypted stores and the real queue."""
    from dataclasses import replace
    from uuid import uuid4

    from client.app import live_institution_runtime
    from shared.contracts.capture_grants import CaptureCredential
    from client.app.institution_store import InstitutionLocalStore
    from client.tests.test_p3_persistent_upload import (
        PersistentUploadQueueTests, _IngestionService, _Tokens,
    )
    from client.tests.test_ray_101_ui_integration import _report
    from client.workflow.models import PreflightCheck, PreflightSummary, ScreeningParticipantContext
    from client.workflow.participant import AnalysisProfile, CreateSubjectRequest
    from client.workflow.protocol import default_standard_protocol

    # Reuse the immutable encrypted segment/envelope fixture; keep its actual
    # StateStore, and put its spool where the packaged factory expects it.
    pending = PersistentUploadQueueTests()
    pending.setUp()
    data_root = pending.root
    pending.root = data_root / "spool"
    pending.root.mkdir()
    segment = pending._seal(0)
    credential = CaptureCredential(session_id=pending.session_id, kind="grant", token="packaged-grant-secret-123456")
    pending._commit(segment, credential=credential)
    institution = InstitutionLocalStore.open(
        data_root / "institution", key_provider=pending.keys, query_index_key=b"q" * 32,
    )
    upload = None
    try:
        tenant_id = str(uuid4())
        subject = institution.create(CreateSubjectRequest(
            tenant_id=tenant_id, analysis_profile=AnalysisProfile.unknown(),
        ))
        context = ScreeningParticipantContext(subject.subject_uuid, str(uuid4()))
        # A retained pre-protocol report exists before this launch. It must not
        # acquire a new grant or lose its original UUID to remain readable.
        historic_id = institution.create_engineering_session(
            context, default_standard_protocol().snapshot(),
        )
        institution.finalize(historic_id)
        report = replace(_report(), session_id=historic_id)
        institution.save_report(report)
        session = SimpleNamespace(
            tenant_id=tenant_id,
            client_installation_id=str(pending.envelope.client_installation_id),
            hardware_asset_id=str(pending.envelope.hardware_asset_id),
        )
        access = _Tokens()
        replenishments = []
        # Model an unavailable issuance service, without modifying the empty
        # real pool. Upload authorization remains available independently.
        access.replenish_capture_grants = lambda store, active: replenishments.append((store, active))
        access.hardware_lease_lifecycle = lambda _session: object()
        starts = []

        class AcquisitionProbe:
            def __init__(self, capture, *, prepare_session):
                self.capture = capture
                self.prepare_session = prepare_session

            def set_callbacks(self, **_callbacks):
                pass

            def start(self, session_id):
                starts.append(session_id)

        # Only physical device preflight/acquisition are substituted. Formal
        # session creation, composition, coordinator, UI and persistence are real.
        monkeypatch.setattr(live_institution_runtime, "QtLiveHardwareAcquisition", AcquisitionProbe)
        monkeypatch.setattr(live_institution_runtime, "build_production_preflight", lambda **_kwargs: SimpleNamespace(
            run_preflight=lambda: PreflightSummary((PreflightCheck("device", True),)),
        ))
        runtime = live_institution_runtime.build_live_institution_runtime(
            session=session, access_runtime=access, key_provider=pending.keys,
            institution=institution, physical_store=pending.store,
            startup_run=object(), data_root=data_root,
            export_destination=lambda: None, app_version="test/1", payload_schema="raw-segment/1",
        )
        qtbot.addWidget(runtime.controller.window)
        coordinator = runtime.coordinator
        coordinator.bind_participant(subject_uuid=context.subject_uuid, consent_record_id=context.consent_record_id)
        coordinator.start_new_screening()
        coordinator.confirm_subject()
        coordinator.complete_profile()
        coordinator.confirm_consent()
        assert coordinator.run_preflight()
        assert coordinator.enter_position_guidance()
        for now in (0.0, 3.0):
            coordinator.observe_position(now_seconds=now, contact_ready=True, in_valid_area=True)
        assert institution.available_capture_grants(tenant_id, session.client_installation_id) == 0
        assert not coordinator.start_acquisition()
        assert starts == []
        assert coordinator.state.session_id is None
        assert "采集额度已用尽" in coordinator.state.error.operator_message
        assert institution.db.execute("SELECT session_id FROM institution_sessions").fetchall() == [(historic_id,)]
        assert replenishments == [(institution, session)]

        # Replace only the remote HTTP boundary. The packaged factory creates
        # its actual PersistentUploadQueue and background scheduler.
        remote = _IngestionService()
        remote.close = lambda: None
        monkeypatch.setattr(upload_runtime_module, "HttpIngestionClient", lambda *_args, **_kwargs: remote)
        upload = build_packaged_upload_runtime(
            data_root, SimpleNamespace(base_url="https://upload.invalid", verify=True),
            session, access, pending.keys, institution, pending.store,
        )
        assert pending.store.sync_handoff_state(str(pending.session_id)) == "READY_FOR_NETWORK"
        upload.start()
        qtbot.waitUntil(lambda: pending.store.sync_handoff_state(str(pending.session_id)) == "CLOUD_CONFIRMED", timeout=5000)
        assert remote.put_calls == [0]
        assert len(remote.manifests) == 1
        assert remote.authorizations[0].token == credential.token
        assert remote.authorizations[0].session_id == credential.session_id
        assert segment.path.exists()
        assert runtime.reports.report_document(report.report_id, report.version).session_id == historic_id
        assert institution.available_capture_grants(tenant_id, session.client_installation_id) == 0
        assert institution.db.execute("SELECT session_id FROM institution_sessions").fetchall() == [(historic_id,)]
        assert starts == []
    finally:
        if upload is not None:
            upload.close()
        institution.close()
        pending.tearDown()
