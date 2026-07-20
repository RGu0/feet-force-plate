from __future__ import annotations

import unittest

from client.workflow.coordinator import ScreeningCoordinator
from client.workflow.models import (
    PreflightCheck,
    PreflightSummary,
    QualityOutcome,
    QualityResult,
    ScreeningParticipantContext,
)


class _Preflight:
    def run_preflight(self) -> PreflightSummary:
        return PreflightSummary((PreflightCheck("device", True),))


class _Sessions:
    def __init__(self) -> None:
        self.contexts: list[ScreeningParticipantContext] = []

    def create_session(self, context: ScreeningParticipantContext) -> str:
        self.contexts.append(context)
        return "session-1"

    def mark_incomplete(self, session_id: str) -> None:
        _ = session_id

    def finalize(self, session_id: str) -> None:
        _ = session_id


class _Acquisition:
    def start(self, session_id: str) -> None:
        _ = session_id

    def stop(self, session_id: str) -> None:
        _ = session_id


class _Analysis:
    def analyze(self, session_id: str) -> QualityResult:
        _ = session_id
        return QualityResult(QualityOutcome.VALID)


class _Reports:
    def create_basic_report(self, session_id: str) -> tuple[str, int]:
        _ = session_id
        return ("report-1", 1)

    def export_pdf(self, *args) -> None:
        _ = args

    def print_report(self, *args) -> None:
        _ = args


class _Telemetry:
    def record_error(self, **kwargs) -> None:
        _ = kwargs


class SessionBindingTests(unittest.TestCase):
    def test_session_creation_receives_selected_subject_and_consent_snapshot(self) -> None:
        sessions = _Sessions()
        coordinator = ScreeningCoordinator(
            preflight=_Preflight(),
            sessions=sessions,
            acquisition=_Acquisition(),
            analysis=_Analysis(),
            reports=_Reports(),
            telemetry=_Telemetry(),
        )
        coordinator.bind_participant(
            subject_uuid="subject-1",
            consent_record_id="consent-1",
        )
        coordinator.start_new_screening()
        coordinator.confirm_subject()
        coordinator.complete_profile()
        coordinator.confirm_consent()
        coordinator.run_preflight()

        coordinator.start_acquisition()

        self.assertEqual(
            sessions.contexts,
            [
                ScreeningParticipantContext(
                    subject_uuid="subject-1",
                    consent_record_id="consent-1",
                )
            ],
        )

    def test_acquisition_is_blocked_when_subject_or_consent_is_not_bound(self) -> None:
        sessions = _Sessions()
        coordinator = ScreeningCoordinator(
            preflight=_Preflight(),
            sessions=sessions,
            acquisition=_Acquisition(),
            analysis=_Analysis(),
            reports=_Reports(),
            telemetry=_Telemetry(),
        )
        coordinator.start_new_screening()
        coordinator.confirm_subject()
        coordinator.complete_profile()
        coordinator.confirm_consent()
        coordinator.run_preflight()

        started = coordinator.start_acquisition()

        self.assertFalse(started)
        self.assertEqual(sessions.contexts, [])
        self.assertEqual(coordinator.state.error.code, "E-AUT-001")


if __name__ == "__main__":
    unittest.main()
