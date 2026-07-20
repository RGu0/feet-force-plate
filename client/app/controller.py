from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from PySide6.QtCore import QTimer

from client.workflow.models import WorkflowState

from .pages import PageId
from .qt_shell import ScreeningWindow


class _CoordinatorPort(Protocol):
    @property
    def state(self) -> WorkflowState: ...

    def start_new_screening(self) -> None: ...

    def confirm_subject(self) -> None: ...

    def complete_profile(self) -> None: ...

    def confirm_consent(self) -> None: ...

    def run_preflight(self) -> bool: ...

    def start_acquisition(self) -> bool: ...

    def stop_acquisition(self) -> bool: ...

    def retry_screening(self) -> None: ...

    def export_current_report(self, destination: Path) -> None: ...

    def print_current_report(self) -> None: ...

    def complete_acquisition(self) -> None: ...

    def handle_device_disconnect(self, *, technical_detail: str) -> None: ...

    def start_next_screening(self) -> None: ...


class ApplicationController:
    def __init__(
        self,
        coordinator: _CoordinatorPort,
        *,
        export_destination: Callable[[], Path | None] | None = None,
    ) -> None:
        self._coordinator = coordinator
        self._export_destination = export_destination or (lambda: None)
        self.window = ScreeningWindow(on_action=self.dispatch)
        self.refresh()

    def dispatch(self, action: str) -> None:
        if action in {"VIEW_BASIC_REPORT", "VIEW_SELECTED_REPORT"}:
            self.window.show_page(PageId.REPORT_PREVIEW)
            return
        if action == "EXPORT_PDF":
            destination = self._export_destination()
            if destination is not None:
                self._coordinator.export_current_report(destination)
            return
        if action == "PRINT_REPORT":
            self._coordinator.print_current_report()
            return
        if action == "CONFIRM_CONSENT":
            self._coordinator.confirm_consent()
            self.refresh()
            QTimer.singleShot(0, self._run_preflight)
            return
        handlers = {
            "START_NEW_SCREENING": self._coordinator.start_new_screening,
            "CONFIRM_SUBJECT": self._coordinator.confirm_subject,
            "SAVE_PROFILE": self._coordinator.complete_profile,
            "SKIP_PROFILE": self._coordinator.complete_profile,
            "RECHECK": self._coordinator.run_preflight,
            "START_ACQUISITION": self._coordinator.start_acquisition,
            "STOP_SCREENING": self._coordinator.stop_acquisition,
            "RETRY_SCREENING": self._coordinator.retry_screening,
            "START_NEXT_SCREENING": self._coordinator.start_next_screening,
        }
        try:
            handler = handlers[action]
        except KeyError as exc:
            raise KeyError(f"unsupported application action: {action}") from exc
        handler()
        self.refresh()

    def refresh(self) -> None:
        self.window.present_state(self._coordinator.state)

    def on_acquisition_completed(self) -> None:
        self._coordinator.complete_acquisition()
        self.refresh()

    def on_device_disconnected(self, technical_detail: str) -> None:
        self._coordinator.handle_device_disconnect(technical_detail=technical_detail)
        self.refresh()

    def _run_preflight(self) -> None:
        self._coordinator.run_preflight()
        self.refresh()
