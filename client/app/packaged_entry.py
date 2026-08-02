from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import platform
import sys
from typing import Protocol
from uuid import UUID

from platformdirs import user_data_path
from PySide6.QtWidgets import QApplication, QWidget

from client.spool.state_store import SensitiveBlobCodec, StateStore
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
from .pages import PageId
from .session_lock import LockTimeout, SessionLockController
from .app_icon import application_icon
from .institution_access import InstitutionAccessWindow
from .startup_validation import MandatoryStartupGate


APP_VERSION = "0.1.0"


class ValidationAuditPort(Protocol):
    def record(self, run): ...

    def recent_results(self, device_ref: str, *, limit: int): ...


@dataclass(frozen=True, slots=True)
class DefaultValidationTelemetryRuntime:
    background: AutomaticValidationTelemetryWorker
    cloud_client: ValidationTelemetryUploadClient

    def stop(self) -> None:
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
        activation_code: str,
        password: str,
        confirmation: str,
        hardware_id: str,
    ) -> None:
        complete(
            runtime.activate(
                account,
                activation_code,
                password,
                confirmation,
                hardware_id,
            )
        )

    return InstitutionAccessWindow(
        on_login=login,
        on_activate=activate,
        stable_hardware_id=runtime.discover_hardware_identity(),
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


def _default_validation_audit_trail() -> tuple[ValidationAuditTrail, StateStore]:
    database = (
        Path(user_data_path("FeetForcePlate", "TechFlex", ensure_exists=True))
        / "database"
        / "client.sqlite3"
    )
    store = StateStore(
        database,
        SensitiveBlobCodec(_ValidationOnlyKeyProvider()),
    )
    return ValidationAuditTrail(store), store


def main() -> int:
    """Start the package at P-00 institution access."""

    app = QApplication(sys.argv)
    app.setWindowIcon(application_icon())
    settings = AccessRuntimeSettings.from_environment()
    runtime = None if settings is None else build_client_access_runtime(settings)
    references: dict[str, object] = {}

    def authenticated(session: SeedAuthenticatedInstitutionSession) -> None:
        access.hide()
        audit_trail, audit_store = _default_validation_audit_trail()
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
            app.aboutToQuit.connect(telemetry_runtime.stop)
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
        workbench_holder: dict[str, ScreeningWindow] = {}

        def workbench_factory() -> ScreeningWindow:
            window = ScreeningWindow(
                session_lock_controller=lock_controller,
                protected_operation_active=lambda: (
                    workbench_holder.get("window") is not None
                    and workbench_holder["window"].current_page_id is PageId.ACQUIRING
                ),
            )
            workbench_holder["window"] = window
            return window

        gate = build_mandatory_startup_gate(
            audit_actor_id=session.client_installation_id,
            app_version=APP_VERSION,
            connector=SerialValidationConnector(
                expected_hardware_identity=session.hardware_id
            ),
            audit_trail=audit_trail,
            workbench_factory=workbench_factory,
        )
        references.update(
            gate=gate,
            audit_store=audit_store,
            telemetry_runtime=telemetry_runtime,
            lock_controller=lock_controller,
            workbench_holder=workbench_holder,
        )
        gate.start()

    access = build_institution_access_screen(
        runtime=runtime,
        environment_label=None if settings is None else settings.environment_label,
        on_authenticated=authenticated,
    )
    references.update(access=access, runtime=runtime)
    app.setProperty("seedAccessComposition", references)
    access.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
