from __future__ import annotations

import unittest

from client.workflow.consent import (
    ConsentPolicy,
    ConsentReceipt,
    ConsentRequest,
    ConsentResolutionStatus,
    ConsentWorkflow,
    RequiredConsentDeclined,
)


class _ConsentPort:
    def __init__(
        self,
        valid: ConsentReceipt | None = None,
        *,
        created: ConsentReceipt | None = None,
    ) -> None:
        self.valid = valid
        self.created = created
        self.find_calls: list[tuple[str, str, ConsentPolicy]] = []
        self.create_calls: list[ConsentRequest] = []

    def find_valid(
        self,
        *,
        tenant_id: str,
        subject_uuid: str,
        policy: ConsentPolicy,
    ) -> ConsentReceipt | None:
        self.find_calls.append((tenant_id, subject_uuid, policy))
        return self.valid

    def create(self, request: ConsentRequest) -> ConsentReceipt:
        self.create_calls.append(request)
        if self.created is None:
            raise AssertionError("test did not configure a consent receipt")
        return self.created


class ConsentWorkflowTests(unittest.TestCase):
    def test_matching_valid_consent_is_reused_without_creating_a_new_record(self) -> None:
        policy = ConsentPolicy(
            policy_version="privacy-policy/1.0",
            purpose_codes=("SCREENING_SERVICE",),
            data_categories=("PRESSURE_RAW", "ANALYSIS_PROFILE"),
        )
        receipt = ConsentReceipt(
            consent_record_id="consent-1",
            tenant_id="tenant-a",
            subject_uuid="subject-1",
            policy_version="privacy-policy/1.0",
            purpose_codes=("SCREENING_SERVICE",),
            data_categories=("PRESSURE_RAW", "ANALYSIS_PROFILE"),
        )
        consents = _ConsentPort(valid=receipt)
        workflow = ConsentWorkflow(
            tenant_id="tenant-a",
            terminal_id="terminal-1",
            consents=consents,
        )

        resolution = workflow.resolve("subject-1", policy)

        self.assertEqual(resolution.status, ConsentResolutionStatus.REUSED)
        self.assertEqual(resolution.receipt, receipt)
        self.assertEqual(workflow.state.receipt, receipt)
        self.assertEqual(
            consents.find_calls,
            [("tenant-a", "subject-1", policy)],
        )
        self.assertEqual(consents.create_calls, [])

    def test_policy_change_requires_confirmation_and_decline_creates_nothing(self) -> None:
        old_receipt = ConsentReceipt(
            consent_record_id="consent-old",
            tenant_id="tenant-a",
            subject_uuid="subject-1",
            policy_version="privacy-policy/1.0",
            purpose_codes=("SCREENING_SERVICE",),
            data_categories=("PRESSURE_RAW",),
        )
        consents = _ConsentPort(valid=old_receipt)
        workflow = ConsentWorkflow(
            tenant_id="tenant-a",
            terminal_id="terminal-1",
            consents=consents,
        )
        new_policy = ConsentPolicy(
            policy_version="privacy-policy/2.0",
            purpose_codes=("SCREENING_SERVICE",),
            data_categories=("PRESSURE_RAW", "ANALYSIS_PROFILE"),
        )

        resolution = workflow.resolve("subject-1", new_policy)

        self.assertEqual(
            resolution.status,
            ConsentResolutionStatus.CONFIRMATION_REQUIRED,
        )
        with self.assertRaises(RequiredConsentDeclined):
            workflow.confirm(
                necessary_accepted=False,
                research_accepted=True,
            )
        self.assertEqual(consents.create_calls, [])
        self.assertIsNone(workflow.state.receipt)

    def test_confirmation_records_required_and_optional_research_separately(self) -> None:
        policy = ConsentPolicy(
            policy_version="privacy-policy/2.0",
            purpose_codes=("SCREENING_SERVICE",),
            data_categories=("PRESSURE_RAW", "ANALYSIS_PROFILE"),
            research_purpose_code="ALGORITHM_RESEARCH",
        )
        created = ConsentReceipt(
            consent_record_id="consent-new",
            tenant_id="tenant-a",
            subject_uuid="subject-1",
            policy_version="privacy-policy/2.0",
            purpose_codes=("SCREENING_SERVICE", "ALGORITHM_RESEARCH"),
            data_categories=("PRESSURE_RAW", "ANALYSIS_PROFILE"),
        )
        consents = _ConsentPort(created=created)
        workflow = ConsentWorkflow(
            tenant_id="tenant-a",
            terminal_id="terminal-1",
            consents=consents,
        )
        workflow.resolve("subject-1", policy)

        receipt = workflow.confirm(
            necessary_accepted=True,
            research_accepted=True,
        )

        self.assertEqual(receipt, created)
        self.assertEqual(workflow.state.receipt, created)
        self.assertEqual(
            consents.create_calls,
            [
                ConsentRequest(
                    tenant_id="tenant-a",
                    terminal_id="terminal-1",
                    subject_uuid="subject-1",
                    policy_version="privacy-policy/2.0",
                    purpose_codes=(
                        "SCREENING_SERVICE",
                        "ALGORITHM_RESEARCH",
                    ),
                    data_categories=("PRESSURE_RAW", "ANALYSIS_PROFILE"),
                    evidence_type="OPERATOR_CONFIRMED",
                )
            ],
        )


if __name__ == "__main__":
    unittest.main()
