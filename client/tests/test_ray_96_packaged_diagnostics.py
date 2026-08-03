from __future__ import annotations

import base64
import json
import runpy
import shutil
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from uuid import UUID
from zipfile import ZipFile

import pytest
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from client.app.packaged_entry import (
    PackagedEntryComposition,
    PackagedDiagnosticSupport,
    build_packaged_workbench_factory,
    load_packaged_support_recipient,
)
from client.support import (
    PlatformFamily,
    SafeClientEventName,
    SafeClientEventOutcome,
    SafeClientEventRecorder,
    SafeClientEventStore,
    SafeDiagnosticExporter,
    SafeDiagnosticMetadata,
)
from client.support.diagnostic_export import decrypt_diagnostic_envelope


INSTALLATION_ID = UUID("8be74f4c-916b-4e6b-b78e-f53e7f7b5475")


def _write_recipient(path: Path, private_key: X25519PrivateKey) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": "feetforceplate-support-recipient/1",
                "key_id": "support-test-1",
                "public_key": base64.b64encode(
                    private_key.public_key().public_bytes_raw()
                ).decode("ascii"),
            }
        ),
        encoding="utf-8",
    )
    path.chmod(0o400)


def _recorder(root: Path) -> tuple[SafeClientEventStore, SafeClientEventRecorder]:
    store = SafeClientEventStore(root / "safe-events")
    return store, SafeClientEventRecorder(
        store,
        client_installation_id=INSTALLATION_ID,
        app_version="0.1.0",
        protocol_version="do-p4864-observed-compact-8bit/1",
        data_mode_version="48x64-uint8-column-major/1",
        config_version="client-support/1",
        now=lambda: datetime(2026, 8, 2, 20, 30, tzinfo=UTC),
    )


def _exporter_factory(store: SafeClientEventStore):
    def make(recipient):
        return SafeDiagnosticExporter(
            store,
            recipient,
            SafeDiagnosticMetadata(
                created_at=datetime(2026, 8, 2, 20, 30, tzinfo=UTC),
                platform_family=PlatformFamily.MACOS,
                client_installation_id=INSTALLATION_ID,
                app_version="0.1.0",
                protocol_version="do-p4864-observed-compact-8bit/1",
                data_mode_version="48x64-uint8-column-major/1",
                config_version="client-support/1",
                event_count=len(store.verified_records()),
            ),
        )

    return make


def test_packaged_workbench_exports_only_p11_diagnostic_and_records_safe_lifecycle(
    qtbot, tmp_path: Path
) -> None:
    """Removing the P-11 branch must stop the encrypted bundle while other actions stay inert."""
    private_key = X25519PrivateKey.generate()
    resource = tmp_path / "recipient.json"
    _write_recipient(resource, private_key)
    store, recorder = _recorder(tmp_path)
    assert recorder.record(SafeClientEventName.APPLICATION_STARTED, SafeClientEventOutcome.OK)
    assert recorder.record(SafeClientEventName.AUTH_LOGIN_ACCEPTED, SafeClientEventOutcome.OK)
    destination = tmp_path / "support.ffpdiag"
    notifications: list[str] = []
    support = PackagedDiagnosticSupport.from_resource(
        resource,
        recorder=recorder,
        exporter_factory=_exporter_factory(store),
        choose_destination=lambda: destination,
        notify=notifications.append,
    )
    factory = build_packaged_workbench_factory(diagnostic_support=support)
    window = factory()
    qtbot.addWidget(window)

    window._on_action("EXPORT_DIAGNOSTIC")  # type: ignore[misc]
    window._on_action("RECHECK_SYSTEM")  # type: ignore[misc]

    assert destination.exists()
    assert not notifications
    assert [record.event.name for record in store.verified_records()] == [
        SafeClientEventName.APPLICATION_STARTED,
        SafeClientEventName.AUTH_LOGIN_ACCEPTED,
        SafeClientEventName.DIAGNOSTIC_EXPORT_COMPLETED,
    ]


@pytest.mark.parametrize(
    "resource_kind",
    ("missing", "writable", "malformed", "wrong-schema", "wrong-length"),
)
def test_invalid_packaged_recipient_disables_only_export_without_artifacts(
    tmp_path: Path, resource_kind: str
) -> None:
    """Relaxing recipient validation must not create a final or plaintext diagnostic artifact."""
    private_key = X25519PrivateKey.generate()
    resource = tmp_path / "recipient.json"
    if resource_kind == "writable":
        _write_recipient(resource, private_key)
        resource.chmod(0o664)
    elif resource_kind == "malformed":
        resource.write_text("not-json", encoding="utf-8")
        resource.chmod(0o400)
    elif resource_kind == "wrong-schema":
        _write_recipient(resource, private_key)
        payload = json.loads(resource.read_text(encoding="utf-8"))
        payload["schema_version"] = "wrong/1"
        resource.chmod(0o600)
        resource.write_text(json.dumps(payload), encoding="utf-8")
        resource.chmod(0o400)
    elif resource_kind == "wrong-length":
        _write_recipient(resource, private_key)
        payload = json.loads(resource.read_text(encoding="utf-8"))
        payload["public_key"] = base64.b64encode(b"too-short").decode("ascii")
        resource.chmod(0o600)
        resource.write_text(json.dumps(payload), encoding="utf-8")
        resource.chmod(0o400)

    store, recorder = _recorder(tmp_path)
    destination = tmp_path / "support.ffpdiag"
    notifications: list[str] = []
    support = PackagedDiagnosticSupport.from_resource(
        resource,
        recorder=recorder,
        exporter_factory=_exporter_factory(store),
        choose_destination=lambda: destination,
        notify=notifications.append,
    )

    support.export_diagnostic_bundle()

    assert not destination.exists()
    assert not list(tmp_path.glob("*.zip"))
    assert not list(tmp_path.glob(".ffpdiag-*"))
    assert notifications == ["诊断包导出暂不可用，请联系平台支持。"]
    event = store.verified_records()[-1].event
    assert (event.name, event.outcome, event.error_code) == (
        SafeClientEventName.DIAGNOSTIC_EXPORT_FAILED,
        SafeClientEventOutcome.FAILED,
        "E-SUP-001",
    )


def test_packaged_recipient_loader_accepts_exact_read_only_public_resource(
    tmp_path: Path,
) -> None:
    """Changing the strict resource shape must reject an otherwise valid packaged key."""
    private_key = X25519PrivateKey.generate()
    resource = tmp_path / "recipient.json"
    _write_recipient(resource, private_key)

    recipient = load_packaged_support_recipient(resource)

    assert recipient.key_id == "support-test-1"


def test_spec_stages_an_arbitrarily_named_public_resource_at_fixed_runtime_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Changing the source basename must not change the packaged lookup name or usable mode."""
    private_key = X25519PrivateKey.generate()
    source = tmp_path / "ci-public-key-name.json"
    _write_recipient(source, private_key)
    captured: dict[str, object] = {}

    class _Analysis:
        def __init__(self, *_args, **kwargs) -> None:
            captured["datas"] = kwargs["datas"]
            self.pure = []
            self.scripts = []
            self.binaries = []
            self.datas = []

    monkeypatch.setenv("FEETFORCEPLATE_SUPPORT_RECIPIENT_FILE", str(source))
    monkeypatch.setattr("sys.platform", "linux")
    spec = Path(__file__).parents[1] / "app" / "packaging" / "FeetForcePlate.spec"
    workpath = tmp_path / "pyinstaller-work"
    runpy.run_path(
        str(spec),
        init_globals={
            "SPECPATH": str(spec.parent),
            "workpath": str(workpath),
            "Analysis": _Analysis,
            "PYZ": lambda *_args: object(),
            "EXE": lambda *_args, **_kwargs: object(),
            "COLLECT": lambda *_args, **_kwargs: object(),
        },
    )

    recipient_data = [
        item for item in captured["datas"] if item[1] == "client/app/resources"
    ]
    assert len(recipient_data) == 1
    staged_source, destination_dir = recipient_data[0]
    assert Path(staged_source).name == "support-recipient.json"
    assert destination_dir == "client/app/resources"
    assert Path(staged_source).stat().st_mode & 0o777 == 0o644
    artifact = tmp_path / "onedir" / destination_dir / "support-recipient.json"
    artifact.parent.mkdir(parents=True)
    shutil.copyfile(staged_source, artifact)
    artifact.chmod(0o644)
    assert load_packaged_support_recipient(artifact).key_id == "support-test-1"
    assert str(source) not in json.dumps(captured, default=str)


def test_injectable_entry_composition_starts_without_resource_and_preserves_identity(
    qtbot, tmp_path: Path
) -> None:
    """Splitting recorder identities or failing missing-resource startup must fail formal P-00 composition."""
    persisted_id = UUID("8be74f4c-916b-4e6b-b78e-f53e7f7b5475")
    destination = tmp_path / "support.ffpdiag"

    class _Runtime:
        def __init__(self, recorder) -> None:
            self.client_installation_id = persisted_id
            self._recorder = recorder
            self.closed = 0

        def login(self) -> None:
            self._recorder.record(
                SafeClientEventName.AUTH_LOGIN_ACCEPTED, SafeClientEventOutcome.OK
            )

        def close(self) -> None:
            self.closed += 1

    runtime_holder: dict[str, _Runtime] = {}

    def build_runtime(recorder_factory):
        runtime = _Runtime(recorder_factory(persisted_id))
        runtime_holder["runtime"] = runtime
        return runtime

    composition = PackagedEntryComposition(
        data_root=tmp_path / "platform-data",
        runtime_builder=build_runtime,
        recipient_resource=tmp_path / "missing-recipient.json",
        choose_destination=lambda: destination,
    )

    composition.start()
    runtime_holder["runtime"].login()
    window = composition.workbench_factory()()
    qtbot.addWidget(window)
    window._on_action("RECHECK_SYSTEM")  # type: ignore[misc]
    window._on_action("EXPORT_DIAGNOSTIC")  # type: ignore[misc]
    composition.close()

    assert not destination.exists()
    assert [record.event.name for record in composition.event_store.verified_records()] == [
        SafeClientEventName.APPLICATION_STARTED,
        SafeClientEventName.AUTH_LOGIN_ACCEPTED,
        SafeClientEventName.DIAGNOSTIC_EXPORT_FAILED,
        SafeClientEventName.APPLICATION_EXITED,
    ]
    assert runtime_holder["runtime"].client_installation_id == persisted_id


def test_injectable_entry_composition_uses_runtime_identity_in_export_metadata(
    qtbot, tmp_path: Path
) -> None:
    """Using a generated recorder ID in the encrypted metadata must fail formal composition."""
    persisted_id = UUID("8be74f4c-916b-4e6b-b78e-f53e7f7b5475")
    private_key = X25519PrivateKey.generate()
    resource = tmp_path / "recipient.json"
    _write_recipient(resource, private_key)
    destination = tmp_path / "support.ffpdiag"

    class _Runtime:
        def __init__(self, recorder) -> None:
            self._recorder = recorder
            self.client_installation_id = persisted_id

        def login(self) -> None:
            self._recorder.record(
                SafeClientEventName.AUTH_LOGIN_ACCEPTED, SafeClientEventOutcome.OK
            )

        def close(self) -> None:
            pass

    composition = PackagedEntryComposition(
        data_root=tmp_path / "platform-data",
        runtime_builder=lambda recorder_factory: _Runtime(recorder_factory(persisted_id)),
        recipient_resource=resource,
        choose_destination=lambda: destination,
    )

    composition.start()
    assert composition.runtime is not None
    composition.runtime.login()
    window = composition.workbench_factory()()
    qtbot.addWidget(window)
    window._on_action("EXPORT_DIAGNOSTIC")  # type: ignore[misc]
    composition.close()

    archive = decrypt_diagnostic_envelope(destination.read_bytes(), private_key)
    with ZipFile(BytesIO(archive)) as bundle:
        metadata = json.loads(bundle.read("manifest.json"))
    records = composition.event_store.verified_records()  # type: ignore[union-attr]
    assert UUID(metadata["client_installation_id"]) == persisted_id
    assert {record.event.client_installation_id for record in records} == {persisted_id}
    assert [record.event.name for record in records] == [
        SafeClientEventName.APPLICATION_STARTED,
        SafeClientEventName.AUTH_LOGIN_ACCEPTED,
        SafeClientEventName.DIAGNOSTIC_EXPORT_COMPLETED,
        SafeClientEventName.APPLICATION_EXITED,
    ]
