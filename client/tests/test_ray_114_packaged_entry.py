from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QWidget

from client.app import packaged_entry
from client.app.packaged_entry import (
    DefaultValidationTelemetryRuntime,
    PackagedEntryComposition,
    PackagedShutdown,
    build_mandatory_startup_gate,
)
from client.cloud.runtime import AuthenticatedInstitutionSession
from client.hardware_standardization.runtime import HardwareStartupConnection
from client.sync.runtime import PackagedUploadRuntime
from client.startup_validation.workflow import DeviceNotFound


class _AbsentConnector:
    def connect(self):
        raise DeviceNotFound("absent")


class _AuditTrail:
    def __init__(self) -> None:
        self.runs = []

    def record(self, run):
        self.runs.append(run)
        return f"event-{len(self.runs)}"

    def recent_results(self, _device_ref: str, *, limit: int):
        return ()


def test_packaged_composition_uses_the_mandatory_gate_before_workbench(qtbot) -> None:
    created: list[QWidget] = []
    audit = _AuditTrail()
    gate = build_mandatory_startup_gate(
        terminal_id="terminal-test",
        app_version="0.1.0-test",
        connector=_AbsentConnector(),
        workbench_factory=lambda: created.append(QWidget()) or created[-1],
        quit_application=lambda: None,
        audit_trail=audit,
    )
    qtbot.addWidget(gate.window)

    gate.start()
    qtbot.waitUntil(
        lambda: gate.window.presentation.error_code == "E-DEV-101",
        timeout=2_000,
    )

    assert created == []
    assert gate.workbench is None
    assert gate.window.isVisible()
    assert [run.reason.value for run in audit.runs] == ["DEVICE_NOT_FOUND"]


def test_formal_entry_starts_with_the_p00_institution_access_screen(qtbot) -> None:
    """Catch a regression that sends unregistered users straight to device checks."""

    window = packaged_entry.build_institution_access_screen()
    qtbot.addWidget(window)
    window.show()

    assert window.objectName() == "institutionAccessWindow"
    assert window.findChild(QWidget, "institutionLoginPage").isVisible()


def test_asset_serial_session_starts_hardware_gate_without_usb_identity_matching() -> None:
    """Regression: passing an FFP label to the USB matcher rejects serial-less CH340."""

    class _Transport:
        def close(self) -> None: ...

    class _Hardware:
        def __init__(self) -> None:
            self.expected_identity = "not called"

        def connect_startup(self, *, expected_hardware_identity):
            self.expected_identity = expected_hardware_identity
            return HardwareStartupConnection(
                device_ref="hardware-opaque",
                transport=_Transport(),
                parser=object(),
                hardware_identity=None,
            )

    hardware = _Hardware()

    connection = packaged_entry.build_asset_serial_startup_connector(
        runtime=hardware
    ).connect()

    assert hardware.expected_identity is None
    assert connection.hardware_identity is None


class _AccessRuntime:
    def __init__(self) -> None:
        self.logins = []

    def hardware_connection_ready(self):
        return True

    def login(self, account, password):
        self.logins.append((account, password))
        return AuthenticatedInstitutionSession(
            tenant_id="tenant",
            account_id="account",
            license_id="license",
            hardware_asset_id="hardware-asset",
            hardware_id="FFP-DP4864-000001",
            client_installation_id="installation",
            access_token="access-token-value-at-least-20",
            signed_license="signed-license",
        )

    def activate_inventory(self, *_args):
        raise AssertionError("not used")


def test_configured_access_screen_hands_authenticated_session_forward(qtbot) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QLineEdit, QPushButton

    runtime = _AccessRuntime()
    sessions = []
    window = packaged_entry.build_institution_access_screen(
        runtime=runtime,
        environment_label="联调环境",
        on_authenticated=sessions.append,
    )
    qtbot.addWidget(window)
    window.show()
    window.findChild(QLineEdit, "institutionAccountInput").setText("seed-clinic")
    window.findChild(QLineEdit, "institutionPasswordInput").setText(
        "correct-horse-battery-staple"
    )

    qtbot.mouseClick(
        window.findChild(QPushButton, "LOGIN_INSTITUTION"),
        Qt.MouseButton.LeftButton,
    )

    assert runtime.logins == [("seed-clinic", "correct-horse-battery-staple")]
    assert len(sessions) == 1
    assert window.findChild(QWidget, "accessEnvironmentLabel").isVisible()


def test_packaged_shutdown_is_idempotent_and_preserves_real_resource_order() -> None:
    """Reordering upload/stores/telemetry/access shutdown or double close must fail."""

    class _Recorder:
        def __init__(self) -> None:
            self.events = []

        def record(self, name, outcome, **kwargs) -> bool:
            self.events.append((name, outcome, kwargs))
            return True

    order: list[str] = []

    class _Background:
        def stop(self) -> None:
            order.append("telemetry-stop-join")

    class _Cloud:
        def close(self) -> None:
            order.append("telemetry-cloud-close")

    class _AuditStore:
        def close(self) -> None:
            order.append("audit-store-close")

    class _InstitutionStore:
        def close(self) -> None:
            order.append("institution-store-close")

    class _PhysicalStore:
        def recover_interrupted_state(self, *, recovered_at_ns: int) -> None:
            assert recovered_at_ns > 0
            order.append("upload-recover")

        def close(self) -> None:
            order.append("physical-store-close")

    class _UploadScheduler:
        def start(self) -> None:
            order.append("upload-scheduler-start")

        def stop(self) -> None:
            order.append("upload-scheduler-stop")

    class _UploadHttp:
        def close(self) -> None:
            order.append("upload-http-close")

    class _AccessRuntime:
        def close(self) -> None:
            order.append("access-cloud-close-store-close")

    recorder = _Recorder()
    telemetry = DefaultValidationTelemetryRuntime(_Background(), _Cloud())
    physical_store = _PhysicalStore()
    upload_runtime = PackagedUploadRuntime(
        spool_root=Path("/formal-data/spool"),
        key_provider=object(),
        physical_store=physical_store,
        upload_scheduler=_UploadScheduler(),
        http_client=_UploadHttp(),
    )
    upload_runtime.start()
    shutdown = PackagedShutdown(
        recorder=recorder,
        telemetry_runtime=telemetry,
        audit_store=_AuditStore(),
        access_runtime=_AccessRuntime(),
    )
    shutdown.attach_authenticated_resources(
        upload_runtime=upload_runtime,
        institution_store=_InstitutionStore(),
        physical_store=physical_store,
        telemetry_runtime=telemetry,
        audit_store=_AuditStore(),
    )

    shutdown.close()
    shutdown.close()

    assert recorder.events == [
        (
            packaged_entry.SafeClientEventName.APPLICATION_EXITED,
            packaged_entry.SafeClientEventOutcome.OK,
            {},
        )
    ]
    assert order == [
        "upload-recover",
        "upload-scheduler-start",
        "upload-scheduler-stop",
        "upload-http-close",
        "institution-store-close",
        "physical-store-close",
        "telemetry-stop-join",
        "telemetry-cloud-close",
        "audit-store-close",
        "access-cloud-close-store-close",
    ]


def _started_composition(tmp_path: Path, access_runtime: object) -> PackagedEntryComposition:
    composition = PackagedEntryComposition(
        data_root=tmp_path,
        runtime_builder=lambda _factory: access_runtime,
        recipient_resource=tmp_path / "unused-support-recipient.json",
        choose_destination=lambda: None,
    )
    composition.start()
    return composition


def test_authenticated_composition_starts_upload_before_gate_and_lock_does_not_stop_it(
    tmp_path: Path,
) -> None:
    """The UI lock must exercise the same authenticated ownership path as production."""

    order: list[str] = []

    class _AccessRuntime:
        def lock_timeout_minutes(self) -> int:
            return 30

        def verify_password(self, _password: str) -> bool:
            return True

        def current_access_token(self) -> str:
            return "access-token-value-at-least-20"

        def close(self) -> None:
            order.append("access.close")

    class _Closable:
        def __init__(self, name: str) -> None:
            self.name = name

        def close(self) -> None:
            order.append(f"{self.name}.close")

    class _Physical(_Closable):
        def record_successful_online(self, timestamp_ns: int) -> None:
            assert timestamp_ns > 0
            order.append("physical.record_online")

    class _Upload(_Closable):
        def start(self) -> None:
            order.append("upload.start")

    class _Gate:
        last_run = object()

        def start(self) -> None:
            order.append("gate.start")

    access_runtime = _AccessRuntime()
    composition = _started_composition(tmp_path, access_runtime)
    references: dict[str, object] = {}
    audit_store = _Closable("audit")
    institution_store = _Closable("institution")
    physical_store = _Physical("physical")
    upload_runtime = _Upload("upload")
    access = SimpleNamespace(hide=lambda: order.append("access.hide"))

    packaged_entry.compose_authenticated_session(
        session=SimpleNamespace(
            client_installation_id="c03732ad-c781-4364-9d3a-c3ce3ea8488c"
        ),
        data_root=tmp_path,
        runtime=access_runtime,
        settings=SimpleNamespace(base_url="https://cloud.invalid", verify=True),
        composition=composition,
        access=access,
        references=references,
        audit_trail_factory=lambda _root: (object(), audit_store),
        key_provider_factory=object,
        institution_store_opener=lambda *_args, **_kwargs: institution_store,
        physical_store_factory=lambda *_args, **_kwargs: physical_store,
        upload_runtime_builder=lambda *_args: upload_runtime,
        telemetry_runtime_builder=lambda **_kwargs: None,
        telemetry_cloud_client_factory=lambda *_args, **_kwargs: object(),
        gate_builder=lambda **_kwargs: _Gate(),
        connector_builder=lambda: object(),
        live_runtime_builder=lambda **_kwargs: object(),
    )

    assert order.index("upload.start") < order.index("gate.start")
    lock_controller = references["lock_controller"]
    assert isinstance(lock_controller, packaged_entry.SessionLockController)
    lock_controller.lock_now()
    assert lock_controller.state.value == "LOCKED"
    assert "upload.close" not in order

    composition.close()
    assert order.count("upload.close") == 1


@pytest.mark.parametrize(
    ("failure_stage", "expected_closes"),
    [
        (
            "institution-build",
            ["audit.close"],
        ),
        (
            "physical-build",
            ["institution.close", "audit.close"],
        ),
        (
            "upload-build",
            ["institution.close", "physical.close", "audit.close"],
        ),
        (
            "upload-start",
            ["upload.close", "institution.close", "physical.close", "audit.close"],
        ),
        (
            "telemetry-start",
            [
                "telemetry-cloud.close",
                "upload.close",
                "institution.close",
                "physical.close",
                "audit.close",
            ],
        ),
        (
            "gate-start",
            [
                "upload.close",
                "institution.close",
                "physical.close",
                "telemetry.close",
                "audit.close",
            ],
        ),
    ],
)
def test_authenticated_composition_releases_each_acquired_resource_on_failure(
    tmp_path: Path, failure_stage: str, expected_closes: list[str]
) -> None:
    """Construction, start, and telemetry failures must not leak authenticated owners."""

    order: list[str] = []

    class _AccessRuntime:
        def current_access_token(self) -> str:
            return "access-token-value-at-least-20"

        def lock_timeout_minutes(self) -> int:
            return 30

        def verify_password(self, _password: str) -> bool:
            return True

        def close(self) -> None:
            order.append("access.close")

    class _Closable:
        def __init__(self, name: str) -> None:
            self.name = name

        def close(self) -> None:
            order.append(f"{self.name}.close")

    class _Physical(_Closable):
        def record_successful_online(self, _timestamp_ns: int) -> None:
            pass

    class _Upload(_Closable):
        def start(self) -> None:
            if failure_stage == "upload-start":
                raise RuntimeError("upload start failed")

    class _Gate:
        def start(self) -> None:
            if failure_stage == "gate-start":
                raise RuntimeError("gate start failed")

    access_runtime = _AccessRuntime()
    composition = _started_composition(tmp_path, access_runtime)
    audit_store = _Closable("audit")
    institution_store = _Closable("institution")
    physical_store = _Physical("physical")
    upload_runtime = _Upload("upload")
    telemetry_cloud = _Closable("telemetry-cloud")

    def build_upload(*_args):
        if failure_stage == "upload-build":
            raise RuntimeError("upload build failed")
        return upload_runtime

    def start_telemetry(**_kwargs):
        if failure_stage == "telemetry-start":
            raise RuntimeError("telemetry start failed")
        if failure_stage == "gate-start":
            return _Closable("telemetry")
        return None

    def open_institution(*_args, **_kwargs):
        if failure_stage == "institution-build":
            raise RuntimeError("institution build failed")
        return institution_store

    def build_physical(*_args, **_kwargs):
        if failure_stage == "physical-build":
            raise RuntimeError("physical build failed")
        return physical_store

    with pytest.raises(RuntimeError, match="failed"):
        packaged_entry.compose_authenticated_session(
            session=SimpleNamespace(
                client_installation_id="c03732ad-c781-4364-9d3a-c3ce3ea8488c"
            ),
            data_root=tmp_path,
            runtime=access_runtime,
            settings=SimpleNamespace(base_url="https://cloud.invalid", verify=True),
            composition=composition,
            access=SimpleNamespace(hide=lambda: None),
            references={},
            audit_trail_factory=lambda _root: (object(), audit_store),
            key_provider_factory=object,
            institution_store_opener=open_institution,
            physical_store_factory=build_physical,
            upload_runtime_builder=build_upload,
            telemetry_runtime_builder=start_telemetry,
            telemetry_cloud_client_factory=lambda *_args, **_kwargs: telemetry_cloud,
            gate_builder=lambda **_kwargs: _Gate(),
            connector_builder=lambda: object(),
            live_runtime_builder=lambda **_kwargs: object(),
        )

    assert order == expected_closes
    assert "access.close" not in order
    composition.close()
    assert order == [*expected_closes, "access.close"]
