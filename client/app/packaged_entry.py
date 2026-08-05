from __future__ import annotations

from collections.abc import Callable
import base64
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import stat
import sys
from typing import Protocol
from uuid import UUID, uuid4

from platformdirs import user_data_path
from PySide6.QtWidgets import QApplication, QFileDialog, QWidget

from client.spool.state_store import SensitiveBlobCodec, StateStore
from client.support import (
    PlatformFamily,
    SafeClientEventName,
    SafeClientEventOutcome,
    SafeClientEventRecorder,
    SafeClientEventStore,
    SafeDiagnosticExporter,
    SafeDiagnosticMetadata,
    SupportRecipient,
)
from client.cloud.runtime import (
    AccessRuntimeSettings,
    AuthenticatedInstitutionSession as SeedAuthenticatedInstitutionSession,
    ClientAccessRuntime,
    build_client_access_runtime,
)
from client.startup_validation.persistence import ValidationAuditTrail
from client.startup_validation.recovery import FailureEscalationPolicy
from client.startup_validation.serial_connector import SerialValidationConnector
from client.startup_validation.service import DeviceValidationService
from client.startup_validation.telemetry_upload import (
    AutomaticValidationTelemetryWorker,
    ValidationTelemetryCloudClient,
    ValidationTelemetryUploadClient,
    ValidationTelemetryUploadWorker,
)
from client.startup_validation.workflow import (
    StartupValidationCoordinator,
    ValidationConnector,
)

from .qt_shell import ScreeningWindow
from .session_lock import LockTimeout, SessionLockController
from .app_icon import application_icon
from .institution_access import InstitutionAccessWindow
from .startup_validation import MandatoryStartupGate
from .live_institution_runtime import build_live_institution_runtime


APP_VERSION = "0.1.0"


class ValidationAuditPort(Protocol):
    def record(self, run): ...

    def recent_results(self, device_ref: str, *, limit: int): ...


class DiagnosticExporterFactory(Protocol):
    def __call__(self, recipient: SupportRecipient) -> SafeDiagnosticExporter: ...


class AccessRuntimeBuilder(Protocol):
    def __call__(
        self,
        event_recorder_factory: Callable[[UUID], SafeClientEventRecorder],
    ) -> ClientAccessRuntime | None: ...


class PackagedDiagnosticSupport:
    """Fail-closed P-11 support adapter for the packaged client."""

    _UNAVAILABLE_MESSAGE = "诊断包导出暂不可用，请联系平台支持。"

    def __init__(
        self,
        *,
        recipient: SupportRecipient | None,
        recorder: SafeClientEventRecorder,
        exporter_factory: DiagnosticExporterFactory,
        choose_destination: Callable[[], Path | None],
        notify: Callable[[str], None],
    ) -> None:
        self._recipient = recipient
        self._recorder = recorder
        self._exporter_factory = exporter_factory
        self._choose_destination = choose_destination
        self._notify = notify

    @classmethod
    def from_resource(
        cls,
        resource: Path,
        *,
        recorder: SafeClientEventRecorder,
        exporter_factory: DiagnosticExporterFactory,
        choose_destination: Callable[[], Path | None],
        notify: Callable[[str], None],
    ) -> PackagedDiagnosticSupport:
        try:
            recipient = load_packaged_support_recipient(resource)
        except Exception:
            recipient = None
        return cls(
            recipient=recipient,
            recorder=recorder,
            exporter_factory=exporter_factory,
            choose_destination=choose_destination,
            notify=notify,
        )

    def export_diagnostic_bundle(self) -> None:
        try:
            recipient = self._recipient
            if recipient is None:
                raise ValueError("support recipient unavailable")
            destination = self._choose_destination()
            if destination is None:
                return
            self._exporter_factory(recipient).export(destination)
        except Exception:
            self._record_failure()
            self._notify(self._UNAVAILABLE_MESSAGE)
            return
        self._record(SafeClientEventName.DIAGNOSTIC_EXPORT_COMPLETED, SafeClientEventOutcome.OK)

    def _record_failure(self) -> None:
        self._record(
            SafeClientEventName.DIAGNOSTIC_EXPORT_FAILED,
            SafeClientEventOutcome.FAILED,
            error_code="E-SUP-001",
        )

    def _record(
        self,
        name: SafeClientEventName,
        outcome: SafeClientEventOutcome,
        *,
        error_code: str | None = None,
    ) -> None:
        try:
            self._recorder.record(name, outcome, error_code=error_code)
        except Exception:
            pass


def load_packaged_support_recipient(path: Path) -> SupportRecipient:
    """Load one build-selected, read-only X25519 public recipient resource."""
    resource = Path(path)
    try:
        status = resource.lstat()
        if not stat.S_ISREG(status.st_mode) or status.st_mode & (
            stat.S_IWGRP | stat.S_IWOTH
        ):
            raise ValueError("invalid support recipient resource")
        payload = json.loads(
            resource.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_recipient_keys,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError("invalid support recipient resource") from exc
    if not isinstance(payload, dict) or set(payload) != {
        "schema_version",
        "key_id",
        "public_key",
    }:
        raise ValueError("invalid support recipient resource")
    if payload["schema_version"] != "feetforceplate-support-recipient/1":
        raise ValueError("invalid support recipient resource")
    key_id = payload["key_id"]
    public_key_text = payload["public_key"]
    if not isinstance(key_id, str) or not key_id.strip() or not isinstance(public_key_text, str):
        raise ValueError("invalid support recipient resource")
    try:
        public_key = base64.b64decode(public_key_text, validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError("invalid support recipient resource") from exc
    if len(public_key) != 32:
        raise ValueError("invalid support recipient resource")
    try:
        return SupportRecipient.from_public_bytes(key_id, public_key)
    except ValueError as exc:
        raise ValueError("invalid support recipient resource") from exc


def _reject_duplicate_recipient_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate support recipient field")
        result[key] = value
    return result


def build_packaged_workbench_factory(
    *,
    diagnostic_support: PackagedDiagnosticSupport | None = None,
    diagnostic_support_factory: Callable[[Callable[[str], None]], PackagedDiagnosticSupport]
    | None = None,
    session_lock_controller: SessionLockController | None = None,
    protected_operation_active: Callable[[], bool] | None = None,
) -> Callable[[], ScreeningWindow]:
    """Compose the workbench's sole packaged action: P-11 diagnostic export."""
    if diagnostic_support is not None and diagnostic_support_factory is not None:
        raise ValueError("configure one packaged diagnostic support source")

    def workbench_factory() -> ScreeningWindow:
        support = diagnostic_support

        def on_action(action: str) -> None:
            if action == "EXPORT_DIAGNOSTIC" and support is not None:
                support.export_diagnostic_bundle()

        window = ScreeningWindow(
            on_action=on_action,
            session_lock_controller=session_lock_controller,
            protected_operation_active=protected_operation_active,
        )
        if diagnostic_support_factory is not None:
            support = diagnostic_support_factory(window.show_form_error)
        return window

    return workbench_factory


class PackagedShutdown:
    """One ordered, idempotent close boundary for formal packaged ownership."""

    def __init__(
        self,
        *,
        recorder: SafeClientEventRecorder,
        telemetry_runtime: DefaultValidationTelemetryRuntime | None = None,
        audit_store: StateStore | None = None,
        access_runtime: ClientAccessRuntime | None = None,
    ) -> None:
        self._recorder = recorder
        self._telemetry_runtime = telemetry_runtime
        self._audit_store = audit_store
        self._access_runtime = access_runtime
        self._closed = False

    def attach_authenticated_resources(
        self,
        *,
        telemetry_runtime: DefaultValidationTelemetryRuntime | None,
        audit_store: StateStore,
    ) -> None:
        if self._closed:
            raise RuntimeError("packaged shutdown is already closed")
        self._telemetry_runtime = telemetry_runtime
        self._audit_store = audit_store

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._recorder.record(
                SafeClientEventName.APPLICATION_EXITED,
                SafeClientEventOutcome.OK,
            )
        except Exception:
            pass
        self._close(self._telemetry_runtime)
        self._close(self._audit_store)
        self._close(self._access_runtime)

    @staticmethod
    def _close(resource: object | None) -> None:
        if resource is None:
            return
        try:
            close = getattr(resource, "close", None)
            if close is not None:
                close()
        except Exception:
            pass


class PackagedEntryComposition:
    """Injectable P-00 composition with one support store and recorder."""

    def __init__(
        self,
        *,
        data_root: Path,
        runtime_builder: AccessRuntimeBuilder,
        recipient_resource: Path,
        choose_destination: Callable[[], Path | None],
    ) -> None:
        self._data_root = data_root
        self._runtime_builder = runtime_builder
        self._recipient_resource = recipient_resource
        self._choose_destination = choose_destination
        self.event_store: SafeClientEventStore | None = None
        self.recorder: SafeClientEventRecorder | None = None
        self.runtime: ClientAccessRuntime | None = None
        self._client_installation_id: UUID | None = None
        self._shutdown: PackagedShutdown | None = None

    def start(self) -> None:
        if self.recorder is not None:
            return
        event_store = SafeClientEventStore(self._data_root / "support-events")
        recorder_holder: dict[str, SafeClientEventRecorder] = {}

        def event_recorder_factory(client_installation_id: UUID) -> SafeClientEventRecorder:
            recorder = _safe_event_recorder(event_store, client_installation_id)
            recorder_holder["recorder"] = recorder
            self._client_installation_id = client_installation_id
            return recorder

        runtime = self._runtime_builder(event_recorder_factory)
        client_installation_id = self._client_installation_id or uuid4()
        recorder = recorder_holder.get("recorder") or _safe_event_recorder(
            event_store,
            client_installation_id,
        )
        self.event_store = event_store
        self.recorder = recorder
        self.runtime = runtime
        self._client_installation_id = client_installation_id
        self._shutdown = PackagedShutdown(
            recorder=recorder,
            access_runtime=runtime,
        )
        recorder.record(SafeClientEventName.APPLICATION_STARTED, SafeClientEventOutcome.OK)

    def workbench_factory(
        self,
        *,
        session_lock_controller: SessionLockController | None = None,
        protected_operation_active: Callable[[], bool] | None = None,
    ) -> Callable[[], ScreeningWindow]:
        if (
            self.event_store is None
            or self.recorder is None
            or self._client_installation_id is None
        ):
            raise RuntimeError("packaged composition must start before creating P-11")
        return build_packaged_workbench_factory(
            diagnostic_support_factory=_packaged_diagnostic_support_factory(
                event_store=self.event_store,
                recorder=self.recorder,
                client_installation_id=self._client_installation_id,
                recipient_resource=self._recipient_resource,
                choose_destination=self._choose_destination,
            ),
            session_lock_controller=session_lock_controller,
            protected_operation_active=protected_operation_active,
        )

    def attach_authenticated_resources(
        self,
        *,
        telemetry_runtime: DefaultValidationTelemetryRuntime | None,
        audit_store: StateStore,
    ) -> None:
        if self._shutdown is None:
            raise RuntimeError("packaged composition must start before authentication")
        self._shutdown.attach_authenticated_resources(
            telemetry_runtime=telemetry_runtime,
            audit_store=audit_store,
        )

    def close(self) -> None:
        if self._shutdown is not None:
            self._shutdown.close()


@dataclass(slots=True)
class DefaultValidationTelemetryRuntime:
    background: AutomaticValidationTelemetryWorker
    cloud_client: ValidationTelemetryUploadClient
    _closed: bool = False

    def stop(self) -> None:
        self.close()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.background.stop()
        close = getattr(self.cloud_client, "close", None)
        if close is not None:
            close()


def start_default_validation_telemetry_upload(
    *,
    audit_trail: ValidationAuditTrail,
    cloud_client: ValidationTelemetryUploadClient,
    client_installation_id: UUID | str,
    interval_seconds: float = 30.0,
) -> DefaultValidationTelemetryRuntime:
    """Start non-blocking automatic upload after institution authentication."""

    worker = ValidationTelemetryUploadWorker(
        audit_trail,
        cloud_client,
        client_installation_id=UUID(str(client_installation_id)),
    )
    background = AutomaticValidationTelemetryWorker(
        worker,
        interval_seconds=interval_seconds,
    )
    runtime = DefaultValidationTelemetryRuntime(background, cloud_client)
    background.start()
    return runtime


@dataclass(frozen=True)
class AuthenticatedInstitutionSession:
    """Identifiers granted by production authentication, excluding credentials."""

    tenant_id: str
    site_id: str
    terminal_id: str
    account_id: str

    def __post_init__(self) -> None:
        for field_name in ("tenant_id", "site_id", "terminal_id", "account_id"):
            if not getattr(self, field_name).strip():
                raise ValueError(f"{field_name} must not be blank")


class InstitutionAuthenticationRejected(RuntimeError):
    """Production credentials were checked and rejected."""


class InstitutionAuthenticationPort(Protocol):
    def authenticate(
        self, account: str, password: str
    ) -> AuthenticatedInstitutionSession: ...


class StartupGatePort(Protocol):
    def start(self) -> None: ...


class InstitutionApplication:
    """Own the P-00 to mandatory startup-gate production handoff."""

    def __init__(
        self,
        *,
        authentication_port: InstitutionAuthenticationPort | None,
        startup_gate_factory: Callable[
            [AuthenticatedInstitutionSession], StartupGatePort
        ]
        | None,
    ) -> None:
        if (authentication_port is None) != (startup_gate_factory is None):
            raise ValueError(
                "authentication_port and startup_gate_factory must be configured together"
            )
        self._authentication_port = authentication_port
        self._startup_gate_factory = startup_gate_factory
        self.startup_gate: StartupGatePort | None = None
        self.access_window = InstitutionAccessWindow(
            on_login=self._authenticate if authentication_port is not None else None,
            allow_local_test_handoff=False,
        )

    def show(self) -> None:
        self.access_window.show()

    def _authenticate(self, account: str, password: str) -> None:
        authentication_port = self._authentication_port
        startup_gate_factory = self._startup_gate_factory
        if authentication_port is None or startup_gate_factory is None:
            self.access_window.show_login_error(
                "当前版本尚未连接 License 服务，暂不能登录。"
            )
            return
        try:
            session = authentication_port.authenticate(account, password)
        except InstitutionAuthenticationRejected:
            self.access_window.show_login_error(
                "机构账号或登录密码不正确，请检查后重试。"
            )
            return
        except Exception:
            self.access_window.show_login_error(
                "登录服务暂时不可用，请稍后重试。"
            )
            return

        try:
            gate = startup_gate_factory(session)
            self.startup_gate = gate
            gate.start()
        except Exception:
            self.startup_gate = None
            self.access_window.show()
            self.access_window.show_login_error(
                "设备启动检查暂时无法开始，请稍后重试。"
            )
            return
        self.access_window.hide()


class _ValidationOnlyKeyProvider:
    def get_key(self) -> bytes:
        raise RuntimeError("sensitive-data key is unavailable in validation-only startup")


def build_mandatory_startup_gate(
    *,
    audit_actor_id: str | None = None,
    terminal_id: str | None = None,
    app_version: str,
    connector: ValidationConnector | None = None,
    workbench_factory: Callable[[], QWidget] = ScreeningWindow,
    quit_application: Callable[[], None] | None = None,
    audit_trail: ValidationAuditPort | None = None,
) -> MandatoryStartupGate:
    resolved_audit_actor_id = audit_actor_id or terminal_id
    if not resolved_audit_actor_id:
        raise ValueError("audit_actor_id is required")
    resolved_connector = connector or SerialValidationConnector()

    def coordinator_factory(on_presentation):
        policy = (
            FailureEscalationPolicy(history=audit_trail).apply
            if audit_trail is not None
            else None
        )
        return StartupValidationCoordinator(
            connector=resolved_connector,
            service_factory=lambda connection: DeviceValidationService(
                transport=connection.transport,
                parser=connection.parser,
            ),
            terminal_id=resolved_audit_actor_id,
            app_version=app_version,
            on_presentation=on_presentation,
            run_policy=policy,
            run_sink=None if audit_trail is None else audit_trail.record,
        )

    return MandatoryStartupGate(
        coordinator_factory=coordinator_factory,
        workbench_factory=workbench_factory,
        quit_application=quit_application,
    )


def build_asset_serial_startup_connector(*, runtime=None) -> SerialValidationConnector:
    """Require a live board without mistaking its USB metadata for its asset ID.

    The authenticated session's ``hardware_id`` is the scanned sales asset
    serial.  A serial-less CH340 cannot attest that label, so matching it via
    ``stable_hardware_identity`` would reject a valid connected board.  The
    backend binding and later lease own the label; this startup gate owns only
    physical connection and unloaded-board validation.
    """

    return SerialValidationConnector(runtime=runtime)


def build_institution_access_screen(
    *,
    runtime: ClientAccessRuntime | None = None,
    environment_label: str | None = None,
    on_authenticated: Callable[[SeedAuthenticatedInstitutionSession], None] | None = None,
) -> InstitutionAccessWindow:
    """Expose P-00 and wire the production access runtime when configured."""

    if runtime is None:
        return InstitutionAccessWindow(environment_label=environment_label)

    def complete(session: SeedAuthenticatedInstitutionSession) -> None:
        if on_authenticated is not None:
            on_authenticated(session)

    def login(account: str, password: str) -> None:
        complete(runtime.login(account, password))

    def activate(
        account: str,
        asset_serial: str,
        activation_code: str,
        password: str,
        confirmation: str,
    ) -> None:
        complete(
            runtime.activate_inventory(
                account,
                account,
                asset_serial,
                activation_code,
                password,
                confirmation,
            )
        )

    return InstitutionAccessWindow(
        on_login=login,
        on_activate=activate,
        hardware_connected=runtime.hardware_connection_ready(),
        hardware_connection_ready=runtime.hardware_connection_ready,
        environment_label=environment_label,
    )


def build_institution_application(
    *,
    authentication_port: InstitutionAuthenticationPort | None = None,
    startup_gate_factory: Callable[[AuthenticatedInstitutionSession], StartupGatePort]
    | None = None,
) -> InstitutionApplication:
    """Build the formal P-00 owner with an optional production-only handoff."""

    return InstitutionApplication(
        authentication_port=authentication_port,
        startup_gate_factory=startup_gate_factory,
    )


def _local_terminal_id() -> str:
    configured = os.environ.get("FEETFORCEPLATE_TERMINAL_ID", "").strip()
    if configured:
        return configured
    local_identity = platform.node() or "local-terminal"
    digest = hashlib.sha256(local_identity.encode("utf-8")).hexdigest()[:20]
    return f"local-{digest}"


def _platform_data_root() -> Path:
    return Path(user_data_path("FeetForcePlate", "TechFlex", ensure_exists=True))


def _default_validation_audit_trail(
    data_root: Path | None = None,
) -> tuple[ValidationAuditTrail, StateStore]:
    database = (data_root or _platform_data_root()) / "database" / "client.sqlite3"
    store = StateStore(
        database,
        SensitiveBlobCodec(_ValidationOnlyKeyProvider()),
    )
    return ValidationAuditTrail(store), store


def _safe_event_recorder(
    store: SafeClientEventStore,
    client_installation_id: UUID,
) -> SafeClientEventRecorder:
    return SafeClientEventRecorder(
        store,
        client_installation_id=client_installation_id,
        app_version=APP_VERSION,
        protocol_version="do-p4864-observed-compact-8bit/1",
        data_mode_version="48x64-uint8-column-major/1",
        config_version="client-support/1",
    )


def _packaged_support_resource_path() -> Path:
    return Path(__file__).resolve().parent / "resources" / "support-recipient.json"


def _choose_diagnostic_destination() -> Path | None:
    selected, _ = QFileDialog.getSaveFileName(
        None,
        "导出问题诊断包",
        "feetforceplate-diagnostic.ffpdiag",
        "FeetForcePlate 诊断包 (*.ffpdiag)",
    )
    return Path(selected) if selected else None


def _platform_family() -> PlatformFamily:
    if sys.platform == "darwin":
        return PlatformFamily.MACOS
    if sys.platform == "win32":
        return PlatformFamily.WINDOWS
    return PlatformFamily.LINUX


def _packaged_diagnostic_support_factory(
    *,
    event_store: SafeClientEventStore,
    recorder: SafeClientEventRecorder,
    client_installation_id: UUID,
    recipient_resource: Path | None = None,
    choose_destination: Callable[[], Path | None] | None = None,
) -> Callable[[Callable[[str], None]], PackagedDiagnosticSupport]:
    def make(notify: Callable[[str], None]) -> PackagedDiagnosticSupport:
        def exporter_factory(recipient: SupportRecipient) -> SafeDiagnosticExporter:
            return SafeDiagnosticExporter(
                event_store,
                recipient,
                SafeDiagnosticMetadata(
                    created_at=datetime.now(UTC),
                    platform_family=_platform_family(),
                    client_installation_id=client_installation_id,
                    app_version=APP_VERSION,
                    protocol_version="do-p4864-observed-compact-8bit/1",
                    data_mode_version="48x64-uint8-column-major/1",
                    config_version="client-support/1",
                    event_count=len(event_store.verified_records()),
                ),
            )

        return PackagedDiagnosticSupport.from_resource(
            recipient_resource or _packaged_support_resource_path(),
            recorder=recorder,
            exporter_factory=exporter_factory,
            choose_destination=choose_destination or _choose_diagnostic_destination,
            notify=notify,
        )

    return make


def main() -> int:
    """Start the package at P-00 institution access."""

    app = QApplication(sys.argv)
    app.setWindowIcon(application_icon())
    settings = AccessRuntimeSettings.from_environment()
    data_root = _platform_data_root()
    composition = PackagedEntryComposition(
        data_root=data_root,
        runtime_builder=lambda event_recorder_factory: (
            None
            if settings is None
            else build_client_access_runtime(
                settings,
                data_root=data_root,
                event_recorder_factory=event_recorder_factory,
            )
        ),
        recipient_resource=_packaged_support_resource_path(),
        choose_destination=_choose_diagnostic_destination,
    )
    composition.start()
    runtime = composition.runtime
    references: dict[str, object] = {}
    app.aboutToQuit.connect(composition.close)

    def authenticated(session: SeedAuthenticatedInstitutionSession) -> None:
        access.hide()
        audit_trail, audit_store = _default_validation_audit_trail(data_root)
        telemetry_runtime = None
        if runtime is not None and settings is not None:
            telemetry_runtime = start_default_validation_telemetry_upload(
                audit_trail=audit_trail,
                cloud_client=ValidationTelemetryCloudClient(
                    settings.base_url,
                    verify=settings.verify,
                    access_token_provider=runtime.current_access_token,
                ),
                client_installation_id=session.client_installation_id,
            )
        composition.attach_authenticated_resources(
            telemetry_runtime=telemetry_runtime,
            audit_store=audit_store,
        )
        timeout_minutes = runtime.lock_timeout_minutes() if runtime is not None else 30
        timeout = (
            LockTimeout.NEVER
            if timeout_minutes is None
            else LockTimeout(str(timeout_minutes))
        )
        lock_controller = SessionLockController(
            lambda password: bool(runtime and runtime.verify_password(password)),
            timeout=timeout,
        )
        gate_holder: dict[str, object] = {}

        def workbench_factory() -> ScreeningWindow:
            gate = gate_holder.get("gate")
            startup_run = getattr(gate, "last_run", None)
            if startup_run is None or runtime is None:
                raise RuntimeError("authenticated live workbench requires a passed startup run")
            live_runtime = build_live_institution_runtime(
                session=session,
                access_runtime=runtime,
                startup_run=startup_run,
                data_root=data_root,
                export_destination=_choose_diagnostic_destination,
            )
            references["live_runtime"] = live_runtime
            return live_runtime.controller.window

        gate = build_mandatory_startup_gate(
            audit_actor_id=session.client_installation_id,
            app_version=APP_VERSION,
            connector=build_asset_serial_startup_connector(),
            audit_trail=audit_trail,
            workbench_factory=workbench_factory,
        )
        gate_holder["gate"] = gate
        references.update(
            gate=gate,
            audit_store=audit_store,
            telemetry_runtime=telemetry_runtime,
            lock_controller=lock_controller,
            gate_holder=gate_holder,
        )
        gate.start()

    access = build_institution_access_screen(
        runtime=runtime,
        environment_label=None if settings is None else settings.environment_label,
        on_authenticated=authenticated,
    )
    references.update(access=access, runtime=runtime, composition=composition)
    app.setProperty("seedAccessComposition", references)
    access.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
