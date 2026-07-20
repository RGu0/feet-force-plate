from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .protocol import PositionGuidanceState
from .state_machine import ScreeningStep


class ClientAction(StrEnum):
    RECHECK = "RECHECK"
    RETRY_SCREENING = "RETRY_SCREENING"
    CONTACT_SUPPORT = "CONTACT_SUPPORT"


class SessionValidity(StrEnum):
    UNKNOWN = "UNKNOWN"
    VALID = "VALID"
    INVALID = "INVALID"
    INCOMPLETE = "INCOMPLETE"
    FAILED = "FAILED"


class LifecycleStatus(StrEnum):
    DRAFT = "DRAFT"
    PREFLIGHT = "PREFLIGHT"
    ACQUIRING = "ACQUIRING"
    FINALIZING = "FINALIZING"
    CLOSED = "CLOSED"


class QualityOutcome(StrEnum):
    VALID = "VALID"
    INVALID = "INVALID"
    DEGRADED = "DEGRADED"


class ReportStatus(StrEnum):
    NOT_AVAILABLE = "NOT_AVAILABLE"
    BASIC_READY = "BASIC_READY"
    CLOUD_ANALYZING = "CLOUD_ANALYZING"
    FULL_READY = "FULL_READY"
    CLOUD_FAILED = "CLOUD_FAILED"


class UploadStatus(StrEnum):
    LOCAL_ONLY = "LOCAL_ONLY"
    PENDING = "PENDING"
    UPLOADING = "UPLOADING"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    CONFLICT = "CONFLICT"


class AnalysisStatus(StrEnum):
    NOT_REQUESTED = "NOT_REQUESTED"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    UNSUPPORTED = "UNSUPPORTED"


@dataclass(frozen=True, slots=True)
class QualityResult:
    outcome: QualityOutcome


@dataclass(frozen=True, slots=True)
class ClientError:
    code: str
    operator_message: str
    action: ClientAction


@dataclass(frozen=True, slots=True)
class PreflightCheck:
    key: str
    ready: bool
    error_code: str | None = None
    operator_message: str | None = None


@dataclass(frozen=True, slots=True)
class PreflightSummary:
    checks: tuple[PreflightCheck, ...]

    @property
    def ready(self) -> bool:
        return all(check.ready for check in self.checks)

    @property
    def first_failure(self) -> PreflightCheck | None:
        return next((check for check in self.checks if not check.ready), None)


@dataclass(frozen=True, slots=True)
class ScreeningParticipantContext:
    subject_uuid: str
    consent_record_id: str


@dataclass(frozen=True, slots=True)
class WorkflowState:
    step: ScreeningStep
    session_id: str | None = None
    lifecycle_status: LifecycleStatus = LifecycleStatus.DRAFT
    validity: SessionValidity = SessionValidity.UNKNOWN
    upload_status: UploadStatus = UploadStatus.LOCAL_ONLY
    analysis_status: AnalysisStatus = AnalysisStatus.NOT_REQUESTED
    report_status: ReportStatus = ReportStatus.NOT_AVAILABLE
    report_id: str | None = None
    report_version: int | None = None
    error: ClientError | None = None
    notice: str | None = None
    position_guidance: PositionGuidanceState | None = None
    acquisition_instruction: str | None = None
    planned_duration_seconds: int | None = None
    remaining_seconds: int | None = None
