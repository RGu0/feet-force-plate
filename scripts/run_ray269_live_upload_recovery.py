#!/usr/bin/env python3
"""Exercise one synthetic upload through real restart/recovery boundaries."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
import tempfile
import time
from uuid import UUID, uuid4

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from client.cloud.access_store import ClientAccessStore, KeyringCredentialStore
from client.cloud.runtime import AccessRuntimeSettings, build_client_access_runtime
from client.device.protocol import RawFrame
from client.spool.segments import ImmutableSegmentWriter
from client.spool.state_store import SensitiveBlobCodec, StateStore, ValidSegmentRecord
from client.sync.persistent_upload import (
    HttpIngestionClient,
    PersistentUploadQueue,
    UploadCycleOutcome,
    UploadRetryable,
)
from shared.contracts.client_sync import FormalUploadEnvelope
from shared.contracts.cloud import (
    ConsentCreateRequest,
    SessionVersions,
    SubjectCreateRequest,
    TestProtocol,
)


class _Key:
    def get_key(self) -> bytes:
        return b"r" * 32


class _Clock:
    def __init__(self, value: int) -> None:
        self.value = value

    def __call__(self) -> int:
        return self.value


class _OfflineClient:
    def get_status(self, *_args, **_kwargs):
        raise UploadRetryable("simulated offline service", error_code="E-SYN-503")


class _ResponseLossAfterCompletion:
    """Make the server complete once while withholding its response from the queue."""

    def __init__(self, client) -> None:
        self._client = client
        self.server_completion_observed = False
        self.last_operation: str | None = None

    def _call(self, name: str, *args, **kwargs):
        self.last_operation = name
        return getattr(self._client, name)(*args, **kwargs)

    def get_status(self, *args, **kwargs):
        return self._call("get_status", *args, **kwargs)

    def create_subject(self, *args, **kwargs):
        return self._call("create_subject", *args, **kwargs)

    def create_consent(self, *args, **kwargs):
        return self._call("create_consent", *args, **kwargs)

    def create_session(self, *args, **kwargs):
        return self._call("create_session", *args, **kwargs)

    def list_segments(self, *args, **kwargs):
        return self._call("list_segments", *args, **kwargs)

    def put_segment(self, *args, **kwargs):
        return self._call("put_segment", *args, **kwargs)

    def complete_session(self, *args, **kwargs):
        self._call("complete_session", *args, **kwargs)
        self.server_completion_observed = True
        raise UploadRetryable("simulated completion response loss", error_code="E-SYN-503")

    def __getattr__(self, name: str):
        return getattr(self._client, name)


class _RecordingClient:
    """Counts only mutating calls made by the final resumed queue cycle."""

    def __init__(self, client) -> None:
        self._client = client
        self.mutations = 0

    def create_subject(self, *args, **kwargs):
        self.mutations += 1
        return self._client.create_subject(*args, **kwargs)

    def create_consent(self, *args, **kwargs):
        self.mutations += 1
        return self._client.create_consent(*args, **kwargs)

    def create_session(self, *args, **kwargs):
        self.mutations += 1
        return self._client.create_session(*args, **kwargs)

    def put_segment(self, *args, **kwargs):
        self.mutations += 1
        return self._client.put_segment(*args, **kwargs)

    def complete_session(self, *args, **kwargs):
        self.mutations += 1
        return self._client.complete_session(*args, **kwargs)

    def __getattr__(self, name: str):
        return getattr(self._client, name)


class _RecoveryContractFailure(RuntimeError):
    def __init__(
        self,
        *,
        stage: str,
        outcome: UploadCycleOutcome,
        error_code: str | None,
        operation: str | None,
    ) -> None:
        super().__init__(stage)
        self.stage = stage
        self.outcome = outcome
        self.error_code = error_code
        self.operation = operation


def _evidence() -> dict[str, object]:
    return {
        "schema_version": "ray269-live-upload-recovery/1",
        "offline_queue_persisted": True,
        "server_completed_before_local_confirmation": True,
        "restart_confirmed_without_duplicate_mutation": True,
        "secrets_or_identifiers_included": False,
    }


def _failure_evidence(
    stage: str, outcome: str, error_code: str | None, operation: str | None
) -> dict[str, object]:
    return {
        "schema_version": "ray269-live-upload-recovery/1",
        "failure_category": "recovery_contract",
        "failure_stage": stage,
        "failure_outcome": outcome,
        "failure_error_code": error_code,
        "failure_operation": operation,
        "secrets_or_identifiers_included": False,
    }


def _stored_license_key_id(data_root: Path) -> str:
    store = ClientAccessStore(
        data_root / "database" / "access.sqlite3", KeyringCredentialStore()
    )
    try:
        state = store.load()
        if state is None:
            raise RuntimeError("no stored institution session is available")
        return state.signed_license.key_id
    finally:
        store.close()


def _frame(source_index: int, monotonic_ns: int) -> RawFrame:
    values = np.zeros((48, 64), dtype=np.uint8)
    values.setflags(write=False)
    return RawFrame(
        values=values,
        host_monotonic_ns=monotonic_ns,
        host_wall_time_ns=monotonic_ns,
        source_index=source_index,
        device_frame_seq=None,
        device_timestamp_ns=None,
        quality_flags=frozenset(),
    )


def _synthetic_consent(subject_id: UUID) -> ConsentCreateRequest:
    return ConsentCreateRequest(
        consent_record_id=uuid4(),
        subject_uuid=subject_id,
        policy_version="ray269-synthetic/1",
        purpose_codes=("INTEGRATION_ACCEPTANCE",),
        data_categories=("PRESSURE_RAW",),
        granted_at=datetime.now(UTC),
        evidence_type="OPERATOR_CONFIRMED",
        terminal_signature="ray269-synthetic-consent",
    )


def _synthetic_segment_duration_seconds() -> float:
    return 5.0


def _stage_synthetic_handoff(
    *, root: Path, store: StateStore, key: _Key, session
) -> str:
    now = datetime.now(UTC)
    started_ns = time.time_ns()
    session_id, subject_id = uuid4(), uuid4()
    consent = _synthetic_consent(subject_id)
    envelope = FormalUploadEnvelope(
        session_id=session_id,
        subject=SubjectCreateRequest(subject_uuid=subject_id),
        consent=consent,
        site_id=None,
        client_installation_id=UUID(session.client_installation_id),
        hardware_asset_id=UUID(session.hardware_asset_id),
        test_protocol=TestProtocol(id="ray269-nonclinical", version="1.0"),
        versions=SessionVersions(
            app="ray269-live-upload-recovery/1",
            protocol_profile="synthetic/1",
            payload_schema="raw-segment/1",
            calibration="synthetic/1",
        ),
        config_snapshot={"mode": "synthetic"},
        started_at=now,
    )
    store.put_subject_ref(str(subject_id), b"synthetic-only")
    store.put_consent_record(
        str(consent.consent_record_id),
        str(subject_id),
        b"synthetic-only",
        recorded_at_ns=started_ns,
    )
    writer = ImmutableSegmentWriter(
        root / "spool" / "sessions",
        session_id=str(session_id),
        key_provider=key,
        versions={"payload_schema": "raw-segment/1"},
        segment_duration_seconds=_synthetic_segment_duration_seconds(),
    )
    writer.append(_frame(0, started_ns))
    sealed = writer.append(_frame(1, started_ns + 5_000_000_000))
    if sealed is None:
        raise RuntimeError("synthetic upload segment was not sealed")
    store.commit_valid_session(
        str(session_id),
        subject_uuid=str(subject_id),
        consent_id=str(consent.consent_record_id),
        versions_json=b"{}",
        started_at_ns=started_ns,
        ended_at_ns=started_ns + 5_000_000_000,
        manifest_sha256="0" * 64,
        upload_envelope=envelope,
        segments=(
            ValidSegmentRecord(
                segment_id=sealed.segment_id,
                relative_path=str(sealed.path.relative_to(root / "spool")),
                byte_count=sealed.byte_count,
                sealed_at_ns=sealed.first_source_index,
            ),
        ),
    )
    return str(session_id)


def run_live_recovery(*, settings, data_root: Path) -> dict[str, object]:
    runtime = build_client_access_runtime(settings, data_root=data_root)
    try:
        session = runtime.refresh()
        with tempfile.TemporaryDirectory(prefix="ray269-live-upload-") as directory:
            root = Path(directory)
            key = _Key()
            clock = _Clock(time.time_ns())
            store = StateStore(root / "state.sqlite3", SensitiveBlobCodec(key))
            try:
                session_id = _stage_synthetic_handoff(
                    root=root, store=store, key=key, session=session
                )
                offline = PersistentUploadQueue(
                    store, root / "spool", key, _OfflineClient(),
                    now_ns=clock, random_fraction=lambda: 0.0,
                )
                if offline.upload_next(runtime) is not UploadCycleOutcome.DEFERRED:
                    raise RuntimeError("offline handoff was not persisted for retry")
            finally:
                store.close()

            clock.value += 60_000_000_000
            store = StateStore(root / "state.sqlite3", SensitiveBlobCodec(key))
            client = HttpIngestionClient(
                settings.base_url,
                terminal_id=UUID(session.client_installation_id),
                verify=settings.verify,
            )
            try:
                response_loss = _ResponseLossAfterCompletion(client)
                interrupted = PersistentUploadQueue(
                    store, root / "spool", key, response_loss,
                    now_ns=clock, random_fraction=lambda: 0.0,
                )
                interrupted_outcome = interrupted.upload_next(runtime)
                if interrupted_outcome is not UploadCycleOutcome.DEFERRED:
                    raise _RecoveryContractFailure(
                        stage="completion_response_loss",
                        outcome=interrupted_outcome,
                        error_code=store.sync_handoff_retry_state(session_id)[2],
                        operation=response_loss.last_operation,
                    )
                if not response_loss.server_completion_observed:
                    raise RuntimeError("server completion did not occur before restart")
            finally:
                client.close()
                store.close()

            clock.value += 60_000_000_000
            store = StateStore(root / "state.sqlite3", SensitiveBlobCodec(key))
            client = HttpIngestionClient(
                settings.base_url,
                terminal_id=UUID(session.client_installation_id),
                verify=settings.verify,
            )
            try:
                resumed_client = _RecordingClient(client)
                resumed = PersistentUploadQueue(
                    store, root / "spool", key, resumed_client,
                    now_ns=clock, random_fraction=lambda: 0.0,
                )
                if resumed.upload_next(runtime) is not UploadCycleOutcome.CONFIRMED:
                    raise RuntimeError("restart did not confirm the completed handoff")
                if resumed_client.mutations != 0:
                    raise RuntimeError("restart performed duplicate remote mutation")
            finally:
                client.close()
                store.close()
    finally:
        runtime.close()
    return _evidence()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--ca-file", type=Path, required=True)
    parser.add_argument("--license-public-key-file", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        settings = AccessRuntimeSettings._from_values(
            raw_url=args.base_url,
            integration_mode=True,
            ca_bundle=str(args.ca_file),
            license_key_id=_stored_license_key_id(args.data_root),
            public_key_file=args.license_public_key_file,
        )
        result = run_live_recovery(settings=settings, data_root=args.data_root)
        exit_code = 0
    except _RecoveryContractFailure as exc:
        result = _failure_evidence(
            exc.stage, exc.outcome.value, exc.error_code, exc.operation
        )
        exit_code = 2
    except Exception as exc:
        result = {
            "schema_version": "ray269-live-upload-recovery/1",
            "secrets_or_identifiers_included": False,
            "failure_category": type(exc).__name__,
        }
        exit_code = 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
