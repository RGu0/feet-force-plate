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
from client.startup_validation.persistence import ValidationAuditTrail
from client.startup_validation.recovery import FailureEscalationPolicy
from client.startup_validation.serial_connector import SerialValidationConnector
from client.startup_validation.service import DeviceValidationService
from client.startup_validation.workflow import (
    StartupValidationCoordinator,
    ValidationConnector,
)

from .qt_shell import ScreeningWindow
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
    """Start the package through the mandatory local device-validation gate."""

    app = QApplication(sys.argv)
    audit_trail, store = _default_validation_audit_trail()
    gate = build_mandatory_startup_gate(
        terminal_id=_local_terminal_id(),
        app_version=APP_VERSION,
        audit_trail=audit_trail,
    )
    gate.start()
    try:
        return app.exec()
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
