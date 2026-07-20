from __future__ import annotations

import unittest

from client.workflow.participant import (
    AnalysisProfile,
    CreateSubjectRequest,
    FieldState,
    ExternalIdType,
    ExternalSubjectIdInput,
    OptionalField,
    ParticipantWorkflow,
    SubjectLookupRequest,
    SubjectResolution,
    SubjectResolutionStatus,
    SubjectSummary,
    TenantBoundaryError,
)


class _SubjectPort:
    def __init__(
        self,
        resolution: SubjectResolution | None = None,
        *,
        created_subject: SubjectSummary | None = None,
    ) -> None:
        self.resolution = resolution or SubjectResolution(
            status=SubjectResolutionStatus.NOT_FOUND
        )
        self.created_subject = created_subject or SubjectSummary(
            "subject-created",
            "tenant-a",
            "临时034",
        )
        self.lookups: list[SubjectLookupRequest] = []
        self.created: list[CreateSubjectRequest] = []
        self.profile_updates: list[tuple[str, str, AnalysisProfile]] = []

    def resolve(self, request: SubjectLookupRequest) -> SubjectResolution:
        self.lookups.append(request)
        return self.resolution

    def create(self, request: CreateSubjectRequest) -> SubjectSummary:
        self.created.append(request)
        return self.created_subject

    def update_profile(
        self,
        *,
        tenant_id: str,
        subject_uuid: str,
        profile: AnalysisProfile,
    ) -> None:
        self.profile_updates.append((tenant_id, subject_uuid, profile))


class _AuditPort:
    def __init__(self) -> None:
        self.accesses: list[tuple[str, str, str]] = []
        self.exports: list[tuple[str, str, str, int, str]] = []

    def record_subject_access(
        self,
        *,
        tenant_id: str,
        subject_uuid: str,
        purpose: str,
    ) -> None:
        self.accesses.append((tenant_id, subject_uuid, purpose))

    def record_subject_export(
        self,
        *,
        tenant_id: str,
        subject_uuid: str,
        report_id: str,
        report_version: int,
        purpose: str,
    ) -> None:
        self.exports.append(
            (tenant_id, subject_uuid, report_id, report_version, purpose)
        )


class ParticipantWorkflowTests(unittest.TestCase):
    def test_conflicting_institution_id_never_selects_or_merges_a_subject(self) -> None:
        candidates = (
            SubjectSummary("subject-1", "tenant-a", "**1234"),
            SubjectSummary("subject-2", "tenant-a", "**1234"),
        )
        subjects = _SubjectPort(
            SubjectResolution(
                status=SubjectResolutionStatus.CONFLICT,
                candidates=candidates,
            )
        )
        workflow = ParticipantWorkflow(
            tenant_id="tenant-a",
            issuer="site-main",
            subjects=subjects,
            audit=_AuditPort(),
        )

        result = workflow.resolve_external_id(
            ExternalIdType.MEDICAL_RECORD_NUMBER,
            "  A-1234  ",
        )

        self.assertEqual(result.status, SubjectResolutionStatus.CONFLICT)
        self.assertEqual(workflow.state.candidates, candidates)
        self.assertIsNone(workflow.state.selected_subject)
        self.assertEqual(
            subjects.lookups,
            [
                SubjectLookupRequest(
                    tenant_id="tenant-a",
                    issuer="site-main",
                    id_type=ExternalIdType.MEDICAL_RECORD_NUMBER,
                    external_id="A-1234",
                )
            ],
        )

    def test_cross_tenant_candidate_is_rejected_before_selection(self) -> None:
        subjects = _SubjectPort(
            SubjectResolution(
                status=SubjectResolutionStatus.FOUND,
                candidates=(SubjectSummary("subject-x", "tenant-b", "**9000"),),
            )
        )
        workflow = ParticipantWorkflow(
            tenant_id="tenant-a",
            issuer="site-main",
            subjects=subjects,
            audit=_AuditPort(),
        )

        with self.assertRaises(TenantBoundaryError):
            workflow.resolve_external_id(
                ExternalIdType.INSTITUTION_RECORD,
                "R-9000",
            )

        self.assertIsNone(workflow.state.selected_subject)

    def test_optional_field_preserves_missing_meaning(self) -> None:
        provided = OptionalField(state=FieldState.PROVIDED, value=168.0)
        unknown = OptionalField[float](state=FieldState.UNKNOWN)
        declined = OptionalField[float](state=FieldState.DECLINED)

        self.assertEqual(provided.value, 168.0)
        self.assertIsNone(unknown.value)
        self.assertIsNone(declined.value)
        with self.assertRaises(ValueError):
            OptionalField[float](state=FieldState.PROVIDED)
        with self.assertRaises(ValueError):
            OptionalField(state=FieldState.UNKNOWN, value=0.0)

    def test_anonymous_quick_create_uses_unknown_profile_without_identity(self) -> None:
        subjects = _SubjectPort()
        workflow = ParticipantWorkflow(
            tenant_id="tenant-a",
            issuer="site-main",
            subjects=subjects,
            audit=_AuditPort(),
        )

        subject = workflow.create_anonymous()

        self.assertEqual(subject.subject_uuid, "subject-created")
        self.assertEqual(workflow.state.selected_subject, subject)
        self.assertEqual(len(subjects.created), 1)
        request = subjects.created[0]
        self.assertEqual(request.tenant_id, "tenant-a")
        self.assertIsNone(request.external_id)
        self.assertIsNone(request.identity)
        self.assertEqual(request.analysis_profile, AnalysisProfile.unknown())
        for field in request.analysis_profile.fields():
            self.assertEqual(field.state, FieldState.UNKNOWN)
            self.assertIsNone(field.value)

    def test_not_found_id_can_create_with_the_same_institution_context(self) -> None:
        subjects = _SubjectPort()
        workflow = ParticipantWorkflow(
            tenant_id="tenant-a",
            issuer="site-main",
            subjects=subjects,
            audit=_AuditPort(),
        )
        workflow.resolve_external_id(
            ExternalIdType.EXAMINATION_NUMBER,
            " EX-2048 ",
        )

        subject = workflow.create_from_last_lookup(AnalysisProfile.unknown())

        self.assertEqual(subject, workflow.state.selected_subject)
        request = subjects.created[0]
        self.assertEqual(
            request.external_id,
            ExternalSubjectIdInput(
                issuer="site-main",
                id_type=ExternalIdType.EXAMINATION_NUMBER,
                external_id="EX-2048",
            ),
        )

    def test_found_subject_access_is_audited_without_external_id_value(self) -> None:
        subject = SubjectSummary("subject-1", "tenant-a", "**1234")
        subjects = _SubjectPort(
            SubjectResolution(
                status=SubjectResolutionStatus.FOUND,
                candidates=(subject,),
            )
        )
        audit = _AuditPort()
        workflow = ParticipantWorkflow(
            tenant_id="tenant-a",
            issuer="site-main",
            subjects=subjects,
            audit=audit,
        )

        workflow.resolve_external_id(
            ExternalIdType.RESIDENT_NUMBER,
            "RES-1234",
        )

        self.assertEqual(workflow.state.selected_subject, subject)
        self.assertEqual(
            audit.accesses,
            [("tenant-a", "subject-1", "SCREENING_SUBJECT_LOOKUP")],
        )
        self.assertNotIn("RES-1234", repr(audit.accesses))

    def test_selected_subject_profile_preserves_each_field_state(self) -> None:
        subject = SubjectSummary("subject-1", "tenant-a", "**1234")
        subjects = _SubjectPort(
            SubjectResolution(
                status=SubjectResolutionStatus.FOUND,
                candidates=(subject,),
            )
        )
        workflow = ParticipantWorkflow(
            tenant_id="tenant-a",
            issuer="site-main",
            subjects=subjects,
            audit=_AuditPort(),
        )
        workflow.resolve_external_id(
            ExternalIdType.INSTITUTION_RECORD,
            "R-1234",
        )
        profile = AnalysisProfile(
            height_cm=OptionalField(FieldState.PROVIDED, 168.0),
            weight_kg=OptionalField(FieldState.PROVIDED, 62.5),
            condition_tags=OptionalField(FieldState.NONE_REPORTED),
            injury_tags=OptionalField(FieldState.DECLINED),
        )

        workflow.update_selected_profile(profile)

        self.assertEqual(
            subjects.profile_updates,
            [("tenant-a", "subject-1", profile)],
        )

    def test_blank_external_id_is_rejected_before_port_access(self) -> None:
        subjects = _SubjectPort()
        workflow = ParticipantWorkflow(
            tenant_id="tenant-a",
            issuer="site-main",
            subjects=subjects,
            audit=_AuditPort(),
        )

        with self.assertRaises(ValueError):
            workflow.resolve_external_id(
                ExternalIdType.INSTITUTION_RECORD,
                "   ",
            )

        self.assertEqual(subjects.lookups, [])

    def test_report_export_audit_uses_tenant_subject_and_report_version(self) -> None:
        subject = SubjectSummary("subject-1", "tenant-a", "**1234")
        audit = _AuditPort()
        workflow = ParticipantWorkflow(
            tenant_id="tenant-a",
            issuer="site-main",
            subjects=_SubjectPort(
                SubjectResolution(
                    SubjectResolutionStatus.FOUND,
                    (subject,),
                )
            ),
            audit=audit,
        )
        workflow.resolve_external_id(
            ExternalIdType.INSTITUTION_RECORD,
            "R-1234",
        )

        workflow.record_selected_export(report_id="report-1", report_version=2)

        self.assertEqual(
            audit.exports,
            [
                (
                    "tenant-a",
                    "subject-1",
                    "report-1",
                    2,
                    "SCREENING_REPORT_EXPORT",
                )
            ],
        )


if __name__ == "__main__":
    unittest.main()
