from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Generic, Protocol, TypeVar


T = TypeVar("T")


class ExternalIdType(StrEnum):
    INSTITUTION_RECORD = "institution_record"
    MEDICAL_RECORD_NUMBER = "medical_record_number"
    EXAMINATION_NUMBER = "examination_number"
    RESIDENT_NUMBER = "resident_number"


class SubjectResolutionStatus(StrEnum):
    FOUND = "FOUND"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"


class FieldState(StrEnum):
    PROVIDED = "PROVIDED"
    NONE_REPORTED = "NONE_REPORTED"
    DECLINED = "DECLINED"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass(frozen=True, slots=True)
class OptionalField(Generic[T]):
    state: FieldState
    value: T | None = None

    def __post_init__(self) -> None:
        if self.state is FieldState.PROVIDED and self.value is None:
            raise ValueError("PROVIDED fields require a value")
        if self.state is not FieldState.PROVIDED and self.value is not None:
            raise ValueError(f"{self.state} fields cannot carry a value")


def _unknown_field() -> OptionalField:
    return OptionalField(state=FieldState.UNKNOWN)


@dataclass(frozen=True, slots=True)
class AnalysisProfile:
    age_band: OptionalField[str] = field(default_factory=_unknown_field)
    sex: OptionalField[str] = field(default_factory=_unknown_field)
    height_cm: OptionalField[float] = field(default_factory=_unknown_field)
    weight_kg: OptionalField[float] = field(default_factory=_unknown_field)
    condition_tags: OptionalField[tuple[str, ...]] = field(
        default_factory=_unknown_field
    )
    injury_tags: OptionalField[tuple[str, ...]] = field(default_factory=_unknown_field)

    @classmethod
    def unknown(cls) -> AnalysisProfile:
        return cls()

    def fields(self) -> tuple[OptionalField, ...]:
        return (
            self.age_band,
            self.sex,
            self.height_cm,
            self.weight_kg,
            self.condition_tags,
            self.injury_tags,
        )


@dataclass(frozen=True, slots=True)
class IdentityInput:
    name: str | None = None
    contact: str | None = None
    government_id: str | None = None


@dataclass(frozen=True, slots=True)
class ExternalSubjectIdInput:
    issuer: str
    id_type: ExternalIdType
    external_id: str


@dataclass(frozen=True, slots=True)
class CreateSubjectRequest:
    tenant_id: str
    analysis_profile: AnalysisProfile
    external_id: ExternalSubjectIdInput | None = None
    identity: IdentityInput | None = None


class TenantBoundaryError(RuntimeError):
    """Raised when an adapter returns data outside the fixed client tenant."""


@dataclass(frozen=True, slots=True)
class SubjectSummary:
    subject_uuid: str
    tenant_id: str
    masked_external_id: str | None = None


@dataclass(frozen=True, slots=True)
class SubjectLookupRequest:
    tenant_id: str
    issuer: str
    id_type: ExternalIdType
    external_id: str


@dataclass(frozen=True, slots=True)
class SubjectResolution:
    status: SubjectResolutionStatus
    candidates: tuple[SubjectSummary, ...] = ()


@dataclass(frozen=True, slots=True)
class ParticipantState:
    candidates: tuple[SubjectSummary, ...] = ()
    selected_subject: SubjectSummary | None = None
    last_lookup: SubjectLookupRequest | None = None
    resolution_status: SubjectResolutionStatus | None = None


class SubjectPort(Protocol):
    def resolve(self, request: SubjectLookupRequest) -> SubjectResolution: ...

    def create(self, request: CreateSubjectRequest) -> SubjectSummary: ...

    def update_profile(
        self,
        *,
        tenant_id: str,
        subject_uuid: str,
        profile: AnalysisProfile,
    ) -> None: ...


class AuditPort(Protocol):
    def record_subject_access(
        self,
        *,
        tenant_id: str,
        subject_uuid: str,
        purpose: str,
    ) -> None: ...

    def record_subject_export(
        self,
        *,
        tenant_id: str,
        subject_uuid: str,
        report_id: str,
        report_version: int,
        purpose: str,
    ) -> None: ...


class ParticipantWorkflow:
    def __init__(
        self,
        *,
        tenant_id: str,
        issuer: str,
        subjects: SubjectPort,
        audit: AuditPort,
    ) -> None:
        self._tenant_id = tenant_id
        self._issuer = issuer
        self._subjects = subjects
        self._audit = audit
        self._state = ParticipantState()

    @property
    def state(self) -> ParticipantState:
        return self._state

    def reset(self) -> None:
        self._state = ParticipantState()

    def resolve_external_id(
        self,
        id_type: ExternalIdType,
        external_id: str,
    ) -> SubjectResolution:
        normalized_input = external_id.strip()
        if not normalized_input:
            raise ValueError("external subject ID cannot be blank")
        request = SubjectLookupRequest(
            tenant_id=self._tenant_id,
            issuer=self._issuer,
            id_type=id_type,
            external_id=normalized_input,
        )
        resolution = self._subjects.resolve(request)
        if any(candidate.tenant_id != self._tenant_id for candidate in resolution.candidates):
            raise TenantBoundaryError("subject resolution crossed the tenant boundary")
        selected = (
            resolution.candidates[0]
            if resolution.status is SubjectResolutionStatus.FOUND
            and len(resolution.candidates) == 1
            else None
        )
        if selected is not None:
            self._audit.record_subject_access(
                tenant_id=self._tenant_id,
                subject_uuid=selected.subject_uuid,
                purpose="SCREENING_SUBJECT_LOOKUP",
            )
        self._state = ParticipantState(
            candidates=resolution.candidates,
            selected_subject=selected,
            last_lookup=request,
            resolution_status=resolution.status,
        )
        return resolution

    def create_anonymous(
        self,
        profile: AnalysisProfile | None = None,
    ) -> SubjectSummary:
        subject = self._subjects.create(
            CreateSubjectRequest(
                tenant_id=self._tenant_id,
                analysis_profile=profile or AnalysisProfile.unknown(),
            )
        )
        if subject.tenant_id != self._tenant_id:
            raise TenantBoundaryError("created subject crossed the tenant boundary")
        self._state = ParticipantState(selected_subject=subject)
        return subject

    def create_from_last_lookup(self, profile: AnalysisProfile) -> SubjectSummary:
        lookup = self._state.last_lookup
        if (
            lookup is None
            or self._state.resolution_status is not SubjectResolutionStatus.NOT_FOUND
        ):
            raise RuntimeError("subject creation requires a NOT_FOUND lookup")
        subject = self._subjects.create(
            CreateSubjectRequest(
                tenant_id=self._tenant_id,
                analysis_profile=profile,
                external_id=ExternalSubjectIdInput(
                    issuer=lookup.issuer,
                    id_type=lookup.id_type,
                    external_id=lookup.external_id,
                ),
            )
        )
        if subject.tenant_id != self._tenant_id:
            raise TenantBoundaryError("created subject crossed the tenant boundary")
        self._state = ParticipantState(selected_subject=subject)
        return subject

    def update_selected_profile(self, profile: AnalysisProfile) -> None:
        subject = self._state.selected_subject
        if subject is None:
            raise RuntimeError("select a subject before updating the profile")
        self._subjects.update_profile(
            tenant_id=self._tenant_id,
            subject_uuid=subject.subject_uuid,
            profile=profile,
        )

    def record_selected_export(self, *, report_id: str, report_version: int) -> None:
        subject = self._state.selected_subject
        if subject is None:
            raise RuntimeError("select a subject before exporting a report")
        self._audit.record_subject_export(
            tenant_id=self._tenant_id,
            subject_uuid=subject.subject_uuid,
            report_id=report_id,
            report_version=report_version,
            purpose="SCREENING_REPORT_EXPORT",
        )
