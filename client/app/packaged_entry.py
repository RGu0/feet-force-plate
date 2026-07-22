from __future__ import annotations

from collections.abc import Callable
import hashlib
import os
import platform
import sys

from PySide6.QtWidgets import QApplication, QWidget

from client.startup_validation.serial_connector import SerialValidationConnector
from client.startup_validation.service import DeviceValidationService
from client.startup_validation.workflow import (
    StartupValidationCoordinator,
    ValidationConnector,
)

from .qt_shell import ScreeningWindow
from .startup_validation import MandatoryStartupGate


APP_VERSION = "0.1.0"


def build_mandatory_startup_gate(
    *,
    terminal_id: str,
    app_version: str,
    connector: ValidationConnector | None = None,
    workbench_factory: Callable[[], QWidget] = ScreeningWindow,
    quit_application: Callable[[], None] | None = None,
) -> MandatoryStartupGate:
    resolved_connector = connector or SerialValidationConnector()

    def coordinator_factory(on_presentation):
        return StartupValidationCoordinator(
            connector=resolved_connector,
            service_factory=lambda connection: DeviceValidationService(
                transport=connection.transport,
                parser=connection.parser,
            ),
            terminal_id=terminal_id,
            app_version=app_version,
            on_presentation=on_presentation,
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


def main() -> int:
    """Start the package through the mandatory local device-validation gate."""

    app = QApplication(sys.argv)
    gate = build_mandatory_startup_gate(
        terminal_id=_local_terminal_id(),
        app_version=APP_VERSION,
    )
    gate.start()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
