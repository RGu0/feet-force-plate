from __future__ import annotations

from collections.abc import Callable
import hashlib
import os
from pathlib import Path
import platform
import sys
from typing import Protocol

from platformdirs import user_data_path
from PySide6.QtWidgets import QApplication, QWidget

from client.spool.state_store import SensitiveBlobCodec, StateStore
from client.cloud.runtime import (
    AccessRuntimeSettings,
    AuthenticatedInstitutionSession,
    ClientAccessRuntime,
    build_client_access_runtime,
)
from client.startup_validation.persistence import ValidationAuditTrail
from client.startup_validation.recovery import FailureEscalationPolicy
from client.startup_validation.serial_connector import SerialValidationConnector
from client.startup_validation.service import DeviceValidationService
from client.startup_validation.workflow import (
    StartupValidationCoordinator,
    ValidationConnector,
)

from .qt_shell import ScreeningWindow
from .app_icon import application_icon
from .institution_access import InstitutionAccessWindow
from .startup_validation import MandatoryStartupGate


APP_VERSION = "0.1.0"


class ValidationAuditPort(Protocol):
    def record(self, run): ...

    def recent_results(self, device_ref: str, *, limit: int): ...


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
    on_authenticated: Callable[[AuthenticatedInstitutionSession], None] | None = None,
) -> InstitutionAccessWindow:
    """Expose P-00 and wire the production access runtime when configured."""

    if runtime is None:
        return InstitutionAccessWindow(environment_label=environment_label)

    def complete(session: AuthenticatedInstitutionSession) -> None:
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

    def authenticated(session: AuthenticatedInstitutionSession) -> None:
        access.hide()
        audit_trail, audit_store = _default_validation_audit_trail()
        gate = build_mandatory_startup_gate(
            audit_actor_id=session.client_installation_id,
            app_version=APP_VERSION,
            connector=SerialValidationConnector(
                expected_hardware_identity=session.hardware_id
            ),
            audit_trail=audit_trail,
        )
        references.update(gate=gate, audit_store=audit_store)
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
