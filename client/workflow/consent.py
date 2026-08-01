from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ConsentPolicy:
    policy_version: str
    purpose_codes: tuple[str, ...]
    data_categories: tuple[str, ...]
    research_purpose_code: str | None = "ALGORITHM_RESEARCH"

    def accepts_purpose_codes(self, purpose_codes: tuple[str, ...]) -> bool:
        actual = set(purpose_codes)
        if self.research_purpose_code is not None:
            actual.discard(self.research_purpose_code)
        return actual == set(self.purpose_codes)


@dataclass(frozen=True, slots=True)
class ConsentReceipt:
    consent_record_id: str
    tenant_id: str
    subject_uuid: str
    policy_version: str
    purpose_codes: tuple[str, ...]
    data_categories: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ConsentRequest:
    tenant_id: str
    terminal_id: str
    subject_uuid: str
    policy_version: str
    purpose_codes: tuple[str, ...]
    data_categories: tuple[str, ...]
    evidence_type: str


class ConsentResolutionStatus(StrEnum):
    REUSED = "REUSED"
    CONFIRMATION_REQUIRED = "CONFIRMATION_REQUIRED"


class RequiredConsentDeclined(RuntimeError):
    """Necessary processing was not accepted, so screening cannot continue."""


class ConsentBoundaryError(RuntimeError):
    """A consent adapter returned a receipt outside the requested scope."""


@dataclass(frozen=True, slots=True)
class ConsentResolution:
    status: ConsentResolutionStatus
    receipt: ConsentReceipt | None = None


@dataclass(frozen=True, slots=True)
class ConsentState:
    subject_uuid: str | None = None
    policy: ConsentPolicy | None = None
    receipt: ConsentReceipt | None = None


class ConsentPort(Protocol):
    def find_valid(
        self,
        *,
        tenant_id: str,
        subject_uuid: str,
        policy: ConsentPolicy,
    ) -> ConsentReceipt | None: ...

    def create(self, request: ConsentRequest) -> ConsentReceipt: ...


class ConsentWorkflow:
    def __init__(
        self,
        *,
        tenant_id: str,
        terminal_id: str,
        consents: ConsentPort,
    ) -> None:
        self._tenant_id = tenant_id
        self._terminal_id = terminal_id
        self._consents = consents
        self._state = ConsentState()

    @property
    def state(self) -> ConsentState:
        return self._state

    def reset(self) -> None:
        self._state = ConsentState()

    def resolve(self, subject_uuid: str, policy: ConsentPolicy) -> ConsentResolution:
        receipt = self._consents.find_valid(
            tenant_id=self._tenant_id,
            subject_uuid=subject_uuid,
            policy=policy,
        )
        if receipt is not None and self._matches(receipt, subject_uuid, policy):
            self._state = ConsentState(
                subject_uuid=subject_uuid,
                policy=policy,
                receipt=receipt,
            )
            return ConsentResolution(ConsentResolutionStatus.REUSED, receipt)
        self._state = ConsentState(subject_uuid=subject_uuid, policy=policy)
        return ConsentResolution(ConsentResolutionStatus.CONFIRMATION_REQUIRED)

    def confirm(
        self,
        *,
        necessary_accepted: bool,
        research_accepted: bool,
    ) -> ConsentReceipt:
        if not necessary_accepted:
            raise RequiredConsentDeclined("necessary processing was declined")
        subject_uuid = self._state.subject_uuid
        policy = self._state.policy
        if subject_uuid is None or policy is None:
            raise RuntimeError("resolve consent before confirming it")
        purpose_codes = policy.purpose_codes
        if research_accepted and policy.research_purpose_code is not None:
            purpose_codes = (*purpose_codes, policy.research_purpose_code)
        request = ConsentRequest(
            tenant_id=self._tenant_id,
            terminal_id=self._terminal_id,
            subject_uuid=subject_uuid,
            policy_version=policy.policy_version,
            purpose_codes=purpose_codes,
            data_categories=policy.data_categories,
            evidence_type="OPERATOR_CONFIRMED",
        )
        receipt = self._consents.create(request)
        if not self._matches_request(receipt, request):
            raise ConsentBoundaryError("created consent did not match its request")
        self._state = ConsentState(
            subject_uuid=subject_uuid,
            policy=policy,
            receipt=receipt,
        )
        return receipt

    def _matches(
        self,
        receipt: ConsentReceipt,
        subject_uuid: str,
        policy: ConsentPolicy,
    ) -> bool:
        return (
            receipt.tenant_id == self._tenant_id
            and receipt.subject_uuid == subject_uuid
            and receipt.policy_version == policy.policy_version
            and policy.accepts_purpose_codes(receipt.purpose_codes)
            and receipt.data_categories == policy.data_categories
        )

    @staticmethod
    def _matches_request(receipt: ConsentReceipt, request: ConsentRequest) -> bool:
        return (
            receipt.tenant_id == request.tenant_id
            and receipt.subject_uuid == request.subject_uuid
            and receipt.policy_version == request.policy_version
            and receipt.purpose_codes == request.purpose_codes
            and receipt.data_categories == request.data_categories
        )
