from __future__ import annotations

from pathlib import Path
from typing import Protocol

from .models import PreflightSummary, QualityResult


class PreflightPort(Protocol):
    def run_preflight(self) -> PreflightSummary: ...


class SessionPort(Protocol):
    def create_session(self) -> str: ...

    def mark_incomplete(self, session_id: str) -> None: ...

    def finalize(self, session_id: str) -> None: ...


class AcquisitionPort(Protocol):
    def start(self, session_id: str) -> None: ...

    def stop(self, session_id: str) -> None: ...


class AnalysisPort(Protocol):
    def analyze(self, session_id: str) -> QualityResult: ...


class ReportPort(Protocol):
    def create_basic_report(self, session_id: str) -> tuple[str, int]: ...

    def export_pdf(self, report_id: str, version: int, destination: Path) -> None: ...

    def print_report(self, report_id: str, version: int) -> None: ...


class TelemetryPort(Protocol):
    def record_error(
        self,
        *,
        code: str,
        session_id: str | None,
        technical_detail: str,
    ) -> None: ...
