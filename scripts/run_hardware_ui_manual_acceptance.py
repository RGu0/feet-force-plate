"""Open one typed hardware-failure state for person-assisted UI acceptance.

This local tool never opens a serial device, reads a session, or writes data.
It is deliberately limited to the two RAY-86 recovery presentations that a
person must confirm in the Qt application shell.
"""

from __future__ import annotations

import argparse
import sys

from PySide6.QtWidgets import QApplication

from client.app.controller import ApplicationController
from client.device.session_ui import (
    HardwareRecoveryAction,
    HardwareUiFailure,
    HardwareUiFailureCode,
)
from client.workflow.models import SessionValidity, WorkflowState
from client.workflow.state_machine import ScreeningStep


class ManualAcceptanceCoordinator:
    """Minimal state port used only to render a typed failure safely."""

    def __init__(self) -> None:
        self._state = WorkflowState(
            step=ScreeningStep.ACQUIRING,
            session_id="manual-ui-acceptance",
        )

    @property
    def state(self) -> WorkflowState:
        return self._state

    def handle_hardware_failure(self, *, error) -> None:
        self._state = WorkflowState(
            step=ScreeningStep.INCOMPLETE,
            session_id="manual-ui-acceptance",
            validity=SessionValidity.INCOMPLETE,
            error=error,
        )


def failure_for(scenario: str) -> HardwareUiFailure:
    """Return a fixed typed failure without any transport or raw-data input."""

    if scenario == "device-disconnected":
        return HardwareUiFailure(
            code=HardwareUiFailureCode.DEVICE_DISCONNECTED,
            recovery_action=HardwareRecoveryAction.RECONNECT_DEVICE,
            retry_allowed=True,
            operator_message_key="hardware.failure.device_disconnected",
        )
    if scenario == "local-finalization-failed":
        return HardwareUiFailure(
            code=HardwareUiFailureCode.LOCAL_FINALIZATION_FAILED,
            recovery_action=HardwareRecoveryAction.CONTACT_SUPPORT,
            retry_allowed=False,
            operator_message_key="hardware.failure.local_finalization_failed",
        )
    raise ValueError(f"unsupported manual UI scenario: {scenario}")


def parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scenario",
        required=True,
        choices=("device-disconnected", "local-finalization-failed"),
        help="typed failure presentation to inspect",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    arguments = parse_arguments(argv)
    app = QApplication.instance() or QApplication(sys.argv)
    controller = ApplicationController(ManualAcceptanceCoordinator())
    controller.window.show()
    controller.on_hardware_failure(failure_for(arguments.scenario))
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
