from __future__ import annotations

import unittest

from client.workflow.state_machine import ScreeningStep, SessionStateMachine


class SessionStateMachineTests(unittest.TestCase):
    def test_standard_flow_requires_declared_transitions(self) -> None:
        machine = SessionStateMachine()

        expected_steps = (
            ScreeningStep.HOME,
            ScreeningStep.SUBJECT_IDENTIFICATION,
            ScreeningStep.PROFILE_DETAILS,
            ScreeningStep.CONSENT_CONFIRMATION,
            ScreeningStep.PREFLIGHT,
            ScreeningStep.POSITION_GUIDANCE,
            ScreeningStep.ACQUIRING,
            ScreeningStep.FINALIZING,
            ScreeningStep.BASIC_REPORT,
        )

        self.assertEqual(machine.step, expected_steps[0])
        for step in expected_steps[1:]:
            machine.transition_to(step)
            self.assertEqual(machine.step, step)

    def test_device_disconnect_marks_session_incomplete_and_offers_retry(self) -> None:
        machine = SessionStateMachine()
        for step in (
            ScreeningStep.SUBJECT_IDENTIFICATION,
            ScreeningStep.PROFILE_DETAILS,
            ScreeningStep.CONSENT_CONFIRMATION,
            ScreeningStep.PREFLIGHT,
            ScreeningStep.POSITION_GUIDANCE,
            ScreeningStep.ACQUIRING,
        ):
            machine.transition_to(step)

        machine.mark_incomplete()

        self.assertEqual(machine.step, ScreeningStep.INCOMPLETE)
        machine.retry()
        self.assertEqual(machine.step, ScreeningStep.POSITION_GUIDANCE)


if __name__ == "__main__":
    unittest.main()
