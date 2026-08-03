from __future__ import annotations

import base64
import errno
import hashlib
import json
import multiprocessing
import sys
import types
from io import BytesIO
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from uuid import UUID, uuid5
from zipfile import ZipFile

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from pydantic import ValidationError

from client import support
from client.support import safe_events
from client.support.diagnostic_export import (
    SafeDiagnosticExporter,
    SafeDiagnosticMetadata,
    SupportRecipient,
    decrypt_diagnostic_envelope,
)
from client.support import (
    PlatformFamily,
    SafeClientCounters,
    SafeClientEvent,
    SafeClientEventName,
    SafeClientEventOutcome,
    SafeClientEventRecorder,
    SafeClientEventStore,
)
from shared.contracts.client_sync import canonical_json_bytes


INSTALLATION_ID = UUID("8be74f4c-916b-4e6b-b78e-f53e7f7b5475")
EVENT_1 = UUID("f9d3af2e-7310-40f0-a1f4-9057312238fa")
EVENT_2 = UUID("e505d71d-7f0f-4cbc-9fe8-a46bb7b0c872")
FIXED_NOW = datetime(2026, 8, 2, 18, 30, tzinfo=UTC)
ALL_SENSITIVE_CANARIES = (
    "PW-CANARY-96",
    "ACT-CANARY-96",
    "REFRESH-CANARY-96",
    "LICENSE-CANARY-96",
    "PATIENT-CANARY-96",
    "MRN-CANARY-96",
)


class _StartSignal(Protocol):
    def wait(self) -> bool: ...


class _ResultSink(Protocol):
    def put(self, item: bool) -> None: ...


def safe_event_payload() -> dict[str, object]:
    return {
        "event_id": str(EVENT_1),
        "occurred_at": "2026-08-02T18:30:00Z",
        "name": "APPLICATION_STARTED",
        "outcome": "OK",
        "client_installation_id": str(INSTALLATION_ID),
        "app_version": "0.1.0",
        "protocol_version": "do-p4864-observed-compact-8bit/1",
        "data_mode_version": "48x64-uint8-column-major/1",
        "config_version": "client-support/1",
    }


def test_client_support_package_exports_only_the_safe_event_api() -> None:
    """Removing a package export must not force consumers onto the implementation module."""
    assert support.__all__ == [
        "SafeClientEventName",
        "SafeClientEventOutcome",
        "SafeClientCounters",
        "SafeClientEvent",
        "SafeClientLogRecord",
        "SafeClientEventRecorder",
        "SafeClientEventStore",
        "PlatformFamily",
        "SupportRecipient",
        "SafeDiagnosticMetadata",
        "DiagnosticExportResult",
        "SafeDiagnosticExporter",
    ]


def make_recorder(store: SafeClientEventStore, event_ids: object) -> SafeClientEventRecorder:
    return SafeClientEventRecorder(
        store,
        client_installation_id=INSTALLATION_ID,
        app_version="0.1.0",
        protocol_version="do-p4864-observed-compact-8bit/1",
        data_mode_version="48x64-uint8-column-major/1",
        config_version="client-support/1",
        event_id_factory=event_ids,  # type: ignore[arg-type]
        now=lambda: FIXED_NOW,
    )


def exporter_with_safe_records(tmp_path: Path, public_key: object) -> SafeDiagnosticExporter:
    store = SafeClientEventStore(tmp_path / "safe-support-events")
    recorder = make_recorder(store, iter((EVENT_1, EVENT_2)).__next__)
    assert recorder.record(SafeClientEventName.APPLICATION_STARTED, SafeClientEventOutcome.OK)
    assert recorder.record(
        SafeClientEventName.AUTH_LOGIN_REJECTED,
        SafeClientEventOutcome.REJECTED,
        error_code="E-AUT-001",
    )
    metadata = SafeDiagnosticMetadata(
        created_at=FIXED_NOW,
        platform_family=PlatformFamily.MACOS,
        client_installation_id=INSTALLATION_ID,
        app_version="0.1.0",
        protocol_version="do-p4864-observed-compact-8bit/1",
        data_mode_version="48x64-uint8-column-major/1",
        config_version="client-support/1",
        event_count=2,
    )
    return SafeDiagnosticExporter(
        store,
        SupportRecipient(key_id="test-support-1", public_key=public_key),  # type: ignore[arg-type]
        metadata,
    )


def canonical_authenticated_envelope(private_key: X25519PrivateKey, recipient_key_id: str) -> bytes:
    ephemeral_private_key = X25519PrivateKey.generate()
    ephemeral_public_key = base64.b64encode(
        ephemeral_private_key.public_key().public_bytes_raw()
    ).decode("ascii")
    nonce = b"diagnostic01"
    nonce_text = base64.b64encode(nonce).decode("ascii")
    header = {
        "schema": "ffpdiag/1",
        "recipient_key_id": recipient_key_id,
        "ephemeral_public_key": ephemeral_public_key,
        "nonce": nonce_text,
    }
    content_key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b"ffpdiag/1|" + recipient_key_id.encode("utf-8"),
    ).derive(ephemeral_private_key.exchange(private_key.public_key()))
    ciphertext = AESGCM(content_key).encrypt(nonce, b"test archive", canonical_json_bytes(header))
    return canonical_json_bytes(
        {
            **header,
            "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
            "ciphertext_sha256": hashlib.sha256(ciphertext).hexdigest(),
        }
    )


def _append_safe_event_in_process(
    root_text: str,
    start: _StartSignal,
    results: _ResultSink,
    process_index: int,
) -> None:
    """Append one distinct event after every worker has opened the same store."""
    store = SafeClientEventStore(root_text)
    recorder = make_recorder(
        store,
        iter((uuid5(EVENT_1, f"concurrent-event-{process_index}"),)).__next__,
    )
    start.wait()
    results.put(
        recorder.record(SafeClientEventName.APPLICATION_STARTED, SafeClientEventOutcome.OK)
    )


def test_safe_event_contract_rejects_credential_identity_and_free_text_fields() -> None:
    """Adding an unapproved payload field must reject the event instead of storing it."""
    base = safe_event_payload()
    for field, canary in {
        "password": "PW-CANARY-96",
        "activation_code": "ACT-CANARY-96",
        "refresh_token": "REFRESH-CANARY-96",
        "signed_license": "LICENSE-CANARY-96",
        "patient_name": "PATIENT-CANARY-96",
        "institution_record_number": "MRN-CANARY-96",
        "message": "arbitrary text",
    }.items():
        with pytest.raises(ValidationError):
            SafeClientEvent.model_validate({**base, field: canary})


def test_private_store_writes_hash_chained_mode_0600_records(tmp_path: Path) -> None:
    """Appending a second event must bind it to the first and keep the log private."""
    store = SafeClientEventStore(tmp_path / "safe-support-events")
    recorder = make_recorder(store, iter((EVENT_1, EVENT_2)).__next__)

    assert recorder.record(SafeClientEventName.APPLICATION_STARTED, SafeClientEventOutcome.OK)
    assert recorder.record(
        SafeClientEventName.AUTH_LOGIN_REJECTED,
        SafeClientEventOutcome.REJECTED,
        error_code="E-AUT-001",
    )

    records = store.verified_records()
    assert records[1].previous_sha256 == records[0].sha256
    assert (tmp_path / "safe-support-events" / "events.jsonl").stat().st_mode & 0o777 == 0o600
    assert (tmp_path / "safe-support-events").stat().st_mode & 0o777 == 0o700


def test_private_store_falls_back_to_path_permissions_without_fchmod(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Windows Python versions without fchmod must still create a private store."""
    def unavailable_fchmod(*_args: object) -> None:
        raise AttributeError("fchmod is unavailable")

    monkeypatch.setattr(safe_events.os, "fchmod", unavailable_fchmod)
    store = SafeClientEventStore(tmp_path / "safe-support-events")
    recorder = make_recorder(store, iter((EVENT_1,)).__next__)

    assert recorder.record(SafeClientEventName.APPLICATION_STARTED, SafeClientEventOutcome.OK)
    assert (tmp_path / "safe-support-events" / "events.jsonl").stat().st_mode & 0o777 == 0o600


def test_windows_process_lock_retries_transient_contention(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A contended Windows lock must wait rather than silently dropping an event."""
    calls: list[int] = []
    outcomes: list[OSError | None] = [
        OSError(errno.EACCES, "busy"),
        OSError(errno.EACCES, "busy"),
        None,
        None,
    ]

    def locking(_descriptor: int, mode: int, _size: int) -> None:
        calls.append(mode)
        outcome = outcomes.pop(0)
        if outcome is not None:
            raise outcome

    fake_msvcrt = types.SimpleNamespace(LK_NBLCK=7, LK_UNLCK=8, locking=locking)
    monkeypatch.setitem(sys.modules, "msvcrt", fake_msvcrt)
    monkeypatch.setattr(safe_events.time, "sleep", lambda _seconds: None)

    unlock = safe_events._acquire_windows_lock(42)
    unlock()

    assert calls == [7, 7, 7, 8]


def test_private_store_serializes_concurrent_process_appends(tmp_path: Path) -> None:
    """Independent client processes must leave one continuous, complete hash chain."""
    context = multiprocessing.get_context("spawn")
    root = tmp_path / "safe-support-events"
    worker_count = 12
    start = context.Barrier(worker_count + 1)
    results = context.Queue()
    workers = [
        context.Process(
            target=_append_safe_event_in_process,
            args=(str(root), start, results, index),
        )
        for index in range(worker_count)
    ]
    for worker in workers:
        worker.start()
    try:
        start.wait()
        for worker in workers:
            worker.join(timeout=15)
            assert worker.exitcode == 0

        assert [results.get(timeout=2) for _ in workers] == [True] * worker_count
        records = SafeClientEventStore(root).verified_records()
        assert len(records) == worker_count
        assert all(
            current.previous_sha256 == previous.sha256
            for previous, current in zip(records, records[1:])
        )
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
            worker.join(timeout=2)
        results.close()
        results.join_thread()


def test_event_contract_bounds_counters_and_accepts_only_technical_versions() -> None:
    """Counters and version labels must remain bounded, machine-readable metadata."""
    event = SafeClientEvent.model_validate(
        {
            **safe_event_payload(),
            "counters": {"attempt_count": 0, "duration_ms": 86_400_000},
        }
    )
    assert event.counters == SafeClientCounters(attempt_count=0, duration_ms=86_400_000)
    with pytest.raises(ValidationError):
        SafeClientEvent.model_validate(
            {**safe_event_payload(), "counters": {"pending_event_count": -1}}
        )
    with pytest.raises(ValidationError):
        SafeClientEvent.model_validate({**safe_event_payload(), "app_version": "free text value"})


def test_store_rotates_to_three_generations_and_verifies_one_continuous_chain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rotation must retain only three private generations without breaking the chain."""
    monkeypatch.setattr(safe_events, "MAX_GENERATION_BYTES", 900)
    root = tmp_path / "safe-support-events"
    store = SafeClientEventStore(root)
    event_ids = (uuid5(EVENT_1, str(index)) for index in range(20))
    recorder = make_recorder(store, event_ids.__next__)

    for _ in range(20):
        assert recorder.record(SafeClientEventName.APPLICATION_STARTED, SafeClientEventOutcome.OK)

    generations = [root / "events.jsonl", root / "events.1.jsonl", root / "events.2.jsonl"]
    assert all(path.exists() for path in generations)
    assert not (root / "events.3.jsonl").exists()
    records = store.verified_records()
    assert len(records) < 20
    assert all(
        current.previous_sha256 == previous.sha256
        for previous, current in zip(records, records[1:])
    )


def test_store_recovers_only_an_incomplete_final_line(tmp_path: Path) -> None:
    """A crash fragment at EOF is discarded while prior complete events remain usable."""
    root = tmp_path / "safe-support-events"
    store = SafeClientEventStore(root)
    assert make_recorder(store, iter((EVENT_1,)).__next__).record(
        SafeClientEventName.APPLICATION_STARTED,
        SafeClientEventOutcome.OK,
    )
    events_path = root / "events.jsonl"
    with events_path.open("ab") as handle:
        handle.write(b'{"interrupted":')

    recovered = SafeClientEventStore(root)
    assert len(recovered.verified_records()) == 1
    assert events_path.read_bytes().endswith(b"\n")


def test_store_rejects_interior_corruption(tmp_path: Path) -> None:
    """Mutating a complete line must be rejected instead of silently exporting it."""
    root = tmp_path / "safe-support-events"
    store = SafeClientEventStore(root)
    recorder = make_recorder(store, iter((EVENT_1, EVENT_2)).__next__)
    assert recorder.record(SafeClientEventName.APPLICATION_STARTED, SafeClientEventOutcome.OK)
    assert recorder.record(SafeClientEventName.AUTH_LOGIN_REJECTED, SafeClientEventOutcome.REJECTED)
    events_path = root / "events.jsonl"
    rows = events_path.read_text(encoding="utf-8").splitlines()
    first = json.loads(rows[0])
    first["sha256"] = "0" * 64
    events_path.write_text(json.dumps(first, separators=(",", ":")) + "\n" + rows[1] + "\n", encoding="utf-8")

    with pytest.raises(ValueError):
        SafeClientEventStore(root).verified_records()


def test_recorder_returns_false_without_writing_a_fallback_file_when_store_fails(
    tmp_path: Path,
) -> None:
    """An I/O failure may yield False but must not serialize an exception anywhere else."""

    class FailingStore:
        def append(self, event: SafeClientEvent) -> None:
            raise OSError("simulated private-store failure")

    recorder = make_recorder(FailingStore(), iter((EVENT_1,)).__next__)  # type: ignore[arg-type]
    assert not recorder.record(SafeClientEventName.APPLICATION_STARTED, SafeClientEventOutcome.OK)
    assert list(tmp_path.iterdir()) == []


def test_encrypted_export_has_fixed_archive_and_no_sensitive_canaries(tmp_path: Path) -> None:
    """A diagnostic export must contain only the strict safe archive encrypted for support."""
    private_key = X25519PrivateKey.generate()
    exporter = exporter_with_safe_records(tmp_path, private_key.public_key())
    destination = tmp_path / "support.ffpdiag"

    result = exporter.export(destination)

    payload = destination.read_bytes()
    archive_bytes = decrypt_diagnostic_envelope(payload, private_key)
    with ZipFile(BytesIO(archive_bytes)) as archive:
        assert set(archive.namelist()) == {
            "manifest.json",
            "safe-events.jsonl",
            "integrity.json",
        }
        assert all(info.date_time == (2026, 1, 1, 0, 0, 0) for info in archive.infolist())
        assert all(info.external_attr >> 16 == 0o600 for info in archive.infolist())
        combined = b"".join(archive.read(name) for name in archive.namelist())
    for canary in ALL_SENSITIVE_CANARIES:
        assert canary.encode() not in combined
        assert canary.encode() not in payload
    assert result.ciphertext_sha256 == hashlib.sha256(payload).hexdigest()
    assert destination.stat().st_mode & 0o777 == 0o600


def test_encrypted_export_rejects_extra_field_records_without_artifacts(tmp_path: Path) -> None:
    """An extra field returned by a compromised store must never reach an encrypted package."""
    private_key = X25519PrivateKey.generate()
    exporter = exporter_with_safe_records(tmp_path, private_key.public_key())
    record = exporter._store.verified_records()[0].model_dump(mode="json")  # type: ignore[attr-defined]
    record["event"]["password"] = "PW-CANARY-96"  # type: ignore[index]

    class ExtraFieldStore:
        def verified_records(self) -> tuple[object, ...]:
            return (record,)

    exporter._store = ExtraFieldStore()  # type: ignore[assignment]
    destination = tmp_path / "malformed.ffpdiag"
    with pytest.raises(ValueError, match="safe diagnostic records"):
        exporter.export(destination)
    assert not destination.exists()
    assert not list(tmp_path.glob("*.zip"))
    assert not list(tmp_path.glob(".ffpdiag-*"))


def test_encrypted_export_rejects_broken_chain_digest_without_artifacts(tmp_path: Path) -> None:
    """A hash-chain failure must stop export before any destination is published."""
    private_key = X25519PrivateKey.generate()
    exporter = exporter_with_safe_records(tmp_path, private_key.public_key())
    store_path = tmp_path / "safe-support-events" / "events.jsonl"
    row = json.loads(store_path.read_text(encoding="utf-8").splitlines()[0])
    row["sha256"] = "0" * 64
    store_path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    destination = tmp_path / "broken.ffpdiag"

    with pytest.raises(ValueError, match="invalid safe event digest"):
        exporter.export(destination)
    assert not destination.exists()
    assert not list(tmp_path.glob("*.zip"))
    assert not list(tmp_path.glob(".ffpdiag-*"))


def test_encrypted_export_rejects_invalid_recipient_bytes_without_artifacts(tmp_path: Path) -> None:
    """Invalid recipient bytes must fail before creating a temporary encrypted output."""
    with pytest.raises(ValueError, match="X25519"):
        SupportRecipient.from_public_bytes("test-support-1", b"not-an-x25519-key")
    assert list(tmp_path.iterdir()) == []


def test_encrypted_export_cleans_up_after_destination_failure(tmp_path: Path) -> None:
    """A missing destination directory must leave neither a final nor temporary diagnostic file."""
    private_key = X25519PrivateKey.generate()
    exporter = exporter_with_safe_records(tmp_path, private_key.public_key())
    destination = tmp_path / "missing" / "support.ffpdiag"

    with pytest.raises(ValueError, match="destination directory"):
        exporter.export(destination)
    assert not destination.exists()
    assert not list(tmp_path.rglob("*.zip"))
    assert not list(tmp_path.rglob(".ffpdiag-*"))


def test_encrypted_export_cleans_up_when_atomic_replace_is_interrupted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An interrupted replace must remove the encrypted temporary output and final artifact."""
    private_key = X25519PrivateKey.generate()
    exporter = exporter_with_safe_records(tmp_path, private_key.public_key())
    destination = tmp_path / "interrupted.ffpdiag"

    def interrupted_replace(source: object, target: object) -> None:
        raise OSError("simulated interruption")

    monkeypatch.setattr("client.support.diagnostic_export.os.replace", interrupted_replace)
    with pytest.raises(OSError, match="simulated interruption"):
        exporter.export(destination)
    assert not destination.exists()
    assert not list(tmp_path.glob("*.zip"))
    assert not list(tmp_path.glob(".ffpdiag-*"))


def test_encrypted_export_has_no_fallible_step_after_replacing_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A former destination must publish successfully even if chmod would now fail."""
    private_key = X25519PrivateKey.generate()
    exporter = exporter_with_safe_records(tmp_path, private_key.public_key())
    destination = tmp_path / "existing.ffpdiag"
    destination.write_bytes(b"old diagnostic")

    def interrupted_chmod(path: object, mode: object) -> None:
        raise OSError("simulated post-replace interruption")

    monkeypatch.setattr("client.support.diagnostic_export.os.chmod", interrupted_chmod)
    result = exporter.export(destination)

    assert result.destination == destination
    assert destination.read_bytes() != b"old diagnostic"
    assert destination.stat().st_mode & 0o777 == 0o600


def test_encrypted_export_preserves_existing_destination_when_replace_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed final replace must leave the old bytes and permissions intact."""
    private_key = X25519PrivateKey.generate()
    exporter = exporter_with_safe_records(tmp_path, private_key.public_key())
    destination = tmp_path / "existing.ffpdiag"
    destination.write_bytes(b"old diagnostic")
    destination.chmod(0o640)
    old_mode = destination.stat().st_mode & 0o777

    def interrupted_replace(source: object, target: object) -> None:
        raise OSError("simulated final replacement failure")

    monkeypatch.setattr("client.support.diagnostic_export.os.replace", interrupted_replace)
    with pytest.raises(OSError, match="simulated final replacement failure"):
        exporter.export(destination)
    assert destination.read_bytes() == b"old diagnostic"
    assert destination.stat().st_mode & 0o777 == old_mode
    assert not list(tmp_path.glob(".ffpdiag-*"))


@pytest.mark.parametrize("mutation", ("duplicate", "reordered", "whitespace", "escaped"))
def test_decrypt_rejects_noncanonical_envelope_encodings(
    tmp_path: Path, mutation: str
) -> None:
    """Ambiguous JSON must be rejected before the authenticated payload is decrypted."""
    private_key = X25519PrivateKey.generate()
    exporter = exporter_with_safe_records(tmp_path, private_key.public_key())
    destination = tmp_path / "support.ffpdiag"
    exporter.export(destination)
    payload = destination.read_bytes()
    if mutation == "duplicate":
        altered = payload.replace(
            b'"schema":"ffpdiag/1"', b'"schema":"ffpdiag/1","schema":"ffpdiag/1"'
        )
    elif mutation == "reordered":
        envelope = json.loads(payload)
        altered = json.dumps(
            {name: envelope[name] for name in reversed(tuple(envelope))}, separators=(",", ":")
        ).encode("utf-8")
    elif mutation == "whitespace":
        altered = b" " + payload
    else:
        altered = payload.replace(b"ffpdiag/1", b"ffpdiag\\/1")

    with pytest.raises(ValueError, match="invalid ffpdiag envelope"):
        decrypt_diagnostic_envelope(altered, private_key)


def test_support_recipient_rejects_non_string_identifiers_and_non_bytes_public_keys() -> None:
    """Recipient construction must fail at its public boundary for coercible malformed inputs."""
    public_key = X25519PrivateKey.generate().public_key().public_bytes_raw()
    for key_id in (b"test-support-1", 1):
        with pytest.raises(ValueError, match="key ID"):
            SupportRecipient(key_id=key_id, public_key=X25519PrivateKey.generate().public_key())  # type: ignore[arg-type]
    for invalid_public_key in ("not-bytes", bytearray(public_key), memoryview(public_key), None):
        with pytest.raises(ValueError, match="X25519 bytes"):
            SupportRecipient.from_public_bytes("test-support-1", invalid_public_key)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "recipient_key_id",
    ("", "a" * 129, "équipe", "-support", "support!key"),
)
def test_decrypt_rejects_canonical_authenticated_envelopes_with_invalid_recipient_ids(
    recipient_key_id: str,
) -> None:
    """The decrypt boundary must enforce the same recipient ID contract as the producer."""
    private_key = X25519PrivateKey.generate()
    payload = canonical_authenticated_envelope(private_key, recipient_key_id)

    with pytest.raises(ValueError):
        decrypt_diagnostic_envelope(payload, private_key)


def test_client_support_public_api_constructs_strict_diagnostic_metadata() -> None:
    """A public-only consumer must be able to construct strict metadata with the exported enum."""
    metadata = support.SafeDiagnosticMetadata(
        created_at=FIXED_NOW,
        platform_family=support.PlatformFamily.MACOS,
        client_installation_id=INSTALLATION_ID,
        app_version="0.1.0",
        protocol_version="do-p4864-observed-compact-8bit/1",
        data_mode_version="48x64-uint8-column-major/1",
        config_version="client-support/1",
        event_count=2,
    )

    assert support.PlatformFamily is PlatformFamily
    assert metadata.platform_family is support.PlatformFamily.MACOS


def test_safe_diagnostic_metadata_rejects_coercible_scalar_types() -> None:
    """Metadata scalars must reject strings and booleans instead of silently coercing them."""
    valid = {
        "created_at": FIXED_NOW,
        "platform_family": PlatformFamily.MACOS,
        "client_installation_id": INSTALLATION_ID,
        "app_version": "0.1.0",
        "protocol_version": "do-p4864-observed-compact-8bit/1",
        "data_mode_version": "48x64-uint8-column-major/1",
        "config_version": "client-support/1",
        "event_count": 2,
    }
    for field, value in {
        "created_at": "2026-08-02T18:30:00Z",
        "platform_family": "macos",
        "client_installation_id": str(INSTALLATION_ID),
        "event_count": "2",
        "event_count_bool": True,
    }.items():
        target_field = "event_count" if field == "event_count_bool" else field
        with pytest.raises(ValidationError):
            SafeDiagnosticMetadata(**{**valid, target_field: value})
