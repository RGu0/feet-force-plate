from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import platform
import sys
from typing import Protocol

from platformdirs import user_data_path
from PySide6.QtWidgets import QApplication, QWidget

from client.spool.state_store import SensitiveBlobCodec, StateStore
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
    terminal_id: str,
    app_version: str,
    connector: ValidationConnector | None = None,
    workbench_factory: Callable[[], QWidget] = ScreeningWindow,
    quit_application: Callable[[], None] | None = None,
    audit_trail: ValidationAuditPort | None = None,
) -> MandatoryStartupGate:
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
            terminal_id=terminal_id,
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


def build_institution_access_screen() -> InstitutionAccessWindow:
    """Expose P-00 before startup hardware validation begins.

    The current package does not include the remote License service, so this
    is intentionally a UI-only access boundary.  A later authentication port
    will decide when it may hand off to ``build_mandatory_startup_gate``.
    """

    return InstitutionAccessWindow()


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
    institution_application = build_institution_application()
    institution_application.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
