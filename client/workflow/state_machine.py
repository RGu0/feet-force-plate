from __future__ import annotations

from enum import StrEnum


class ScreeningStep(StrEnum):
    HOME = "HOME"
    SUBJECT_IDENTIFICATION = "SUBJECT_IDENTIFICATION"
    PROFILE_DETAILS = "PROFILE_DETAILS"
    CONSENT_CONFIRMATION = "CONSENT_CONFIRMATION"
    PREFLIGHT = "PREFLIGHT"
    POSITION_GUIDANCE = "POSITION_GUIDANCE"
    ACQUIRING = "ACQUIRING"
    FINALIZING = "FINALIZING"
    BASIC_REPORT = "BASIC_REPORT"
    INCOMPLETE = "INCOMPLETE"
    RETRY_REQUIRED = "RETRY_REQUIRED"
    FAILED = "FAILED"


_STANDARD_NEXT_STEP = {
    ScreeningStep.HOME: ScreeningStep.SUBJECT_IDENTIFICATION,
    ScreeningStep.SUBJECT_IDENTIFICATION: ScreeningStep.PROFILE_DETAILS,
    ScreeningStep.PROFILE_DETAILS: ScreeningStep.CONSENT_CONFIRMATION,
    ScreeningStep.CONSENT_CONFIRMATION: ScreeningStep.PREFLIGHT,
    ScreeningStep.PREFLIGHT: ScreeningStep.POSITION_GUIDANCE,
    ScreeningStep.POSITION_GUIDANCE: ScreeningStep.ACQUIRING,
    ScreeningStep.ACQUIRING: ScreeningStep.FINALIZING,
    ScreeningStep.FINALIZING: ScreeningStep.BASIC_REPORT,
}


class InvalidTransition(ValueError):
    """Raised when a workflow command tries to skip a required step."""


class SessionStateMachine:
    def __init__(self) -> None:
        self._step = ScreeningStep.HOME

    @property
    def step(self) -> ScreeningStep:
        return self._step

    def transition_to(self, target: ScreeningStep) -> None:
        if self._step is ScreeningStep.ACQUIRING and target is ScreeningStep.POSITION_GUIDANCE:
            self._step = target
            return
        expected = _STANDARD_NEXT_STEP.get(self._step)
        if target is not expected:
            raise InvalidTransition(f"cannot transition from {self._step} to {target}")
        self._step = target

    def mark_incomplete(self) -> None:
        if self._step is not ScreeningStep.ACQUIRING:
            raise InvalidTransition(f"cannot mark {self._step} incomplete")
        self._step = ScreeningStep.INCOMPLETE

    def retry(self) -> None:
        if self._step not in {ScreeningStep.INCOMPLETE, ScreeningStep.RETRY_REQUIRED}:
            raise InvalidTransition(f"cannot retry from {self._step}")
        self._step = ScreeningStep.PREFLIGHT

    def mark_retry_required(self) -> None:
        if self._step is not ScreeningStep.FINALIZING:
            raise InvalidTransition(f"cannot require retry from {self._step}")
        self._step = ScreeningStep.RETRY_REQUIRED

    def mark_failed(self) -> None:
        if self._step is not ScreeningStep.FINALIZING:
            raise InvalidTransition(f"cannot fail from {self._step}")
        self._step = ScreeningStep.FAILED
