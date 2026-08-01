"""License/2, hardware lease, and offline quota policy for the seed client."""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Mapping
from uuid import UUID

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from client.spool.state_store import (
    OFFLINE_LIMIT_NS,
    PENDING_BYTE_LIMIT,
    PENDING_SESSION_LIMIT,
    OfflineSnapshot,
)
from shared.contracts.access_control import (
    LicenseDocumentV2,
    LicenseState,
    SignedLicenseV2,
)
from shared.contracts.client_sync import canonical_json_bytes
from shared.contracts.device_policy import GateReason


class PolicyConnectivity(StrEnum):
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"


class PolicyEvidence(StrEnum):
    ONLINE_LEASE_PROVEN = "ONLINE_LEASE_PROVEN"
    OFFLINE_GRACE_NO_GLOBAL_LEASE_PROOF = "OFFLINE_GRACE_NO_GLOBAL_LEASE_PROOF"


@dataclass(frozen=True, slots=True)
class HardwareLeaseSnapshot:
    client_installation_id: UUID
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class SeedLicensePolicyInput:
    evaluated_at: datetime
    monotonic_now_ns: int
    connectivity: PolicyConnectivity
    clock_trusted: bool
    offline: OfflineSnapshot
    client_installation_id: UUID
    lease: HardwareLeaseSnapshot | None = None


@dataclass(frozen=True, slots=True)
class SeedCapabilityDecision:
    allow_new_test: bool
    allow_finalize_current_test: bool
    allow_report_view: bool
    allow_upload: bool
    reasons: tuple[GateReason, ...]
    evidence: PolicyEvidence | None


class AccountHardwareLicenseVerifier:
    """Verify License/2 signature, identity binding, and monotonic version."""

    def __init__(self, public_keys: Mapping[str, bytes]) -> None:
        if not public_keys:
            raise ValueError("at least one License public key is required")
        self._public_keys = {
            key_id: Ed25519PublicKey.from_public_bytes(value)
            for key_id, value in public_keys.items()
        }

    def verify(
        self,
        bundle: SignedLicenseV2,
        *,
        expected_tenant_id: UUID,
        expected_account_id: UUID,
        expected_license_id: UUID,
        expected_hardware_id: str,
        minimum_version: int = 0,
    ) -> LicenseDocumentV2:
        public_key = self._public_keys.get(bundle.key_id)
        if public_key is None:
            raise ValueError("License signature key is unknown")
        try:
            signature = base64.b64decode(bundle.signature, validate=True)
            public_key.verify(signature, canonical_json_bytes(bundle.document))
        except (binascii.Error, InvalidSignature) as exc:
            raise ValueError("License signature is invalid") from exc
        document = bundle.document
        if (
            document.tenant_id != expected_tenant_id
            or document.account_id != expected_account_id
            or document.license_id != expected_license_id
            or document.hardware_id != expected_hardware_id
        ):
            raise ValueError("License account or hardware binding does not match")
        if document.version < minimum_version:
            raise ValueError("License version downgrade is not allowed")
        return document


def evaluate_seed_license_policy(
    document: LicenseDocumentV2,
    state: SeedLicensePolicyInput,
) -> SeedCapabilityDecision:
    reasons: list[GateReason] = []
    if document.status is LicenseState.SUSPENDED:
        reasons.append(GateReason.LICENSE_SUSPENDED)
    elif document.status is LicenseState.REVOKED:
        reasons.append(GateReason.LICENSE_REVOKED)
    elif document.status is not LicenseState.ACTIVE:
        reasons.append(GateReason.LICENSE_INVALID)
    if state.evaluated_at < document.valid_from or state.evaluated_at >= document.valid_until:
        reasons.append(GateReason.LICENSE_EXPIRED)
    if "screening.start" not in document.enabled_features:
        reasons.append(GateReason.FEATURE_DISABLED)
    if not state.clock_trusted:
        reasons.append(GateReason.CLOCK_ROLLBACK)
    if state.offline.pending_session_count >= PENDING_SESSION_LIMIT:
        reasons.append(GateReason.PENDING_SESSION_LIMIT)
    if state.offline.pending_bytes >= PENDING_BYTE_LIMIT:
        reasons.append(GateReason.PENDING_BYTES_LIMIT)

    evidence: PolicyEvidence | None = None
    if state.connectivity is PolicyConnectivity.ONLINE:
        if state.lease is None or state.lease.expires_at <= state.evaluated_at:
            reasons.append(GateReason.LEASE_REQUIRED)
        elif state.lease.client_installation_id != state.client_installation_id:
            reasons.append(GateReason.LEASE_CONFLICT)
        else:
            evidence = PolicyEvidence.ONLINE_LEASE_PROVEN
    else:
        last_online = state.offline.last_successful_online_ns
        if (
            last_online is None
            or state.monotonic_now_ns < last_online
            or state.monotonic_now_ns - last_online > OFFLINE_LIMIT_NS
        ):
            reasons.append(GateReason.OFFLINE_TOO_LONG)
        else:
            evidence = PolicyEvidence.OFFLINE_GRACE_NO_GLOBAL_LEASE_PROOF

    unique_reasons = tuple(dict.fromkeys(reasons))
    return SeedCapabilityDecision(
        allow_new_test=not unique_reasons,
        allow_finalize_current_test=True,
        allow_report_view=True,
        allow_upload=True,
        reasons=unique_reasons,
        evidence=evidence,
    )


__all__ = [
    "AccountHardwareLicenseVerifier",
    "HardwareLeaseSnapshot",
    "PolicyConnectivity",
    "PolicyEvidence",
    "SeedCapabilityDecision",
    "SeedLicensePolicyInput",
    "evaluate_seed_license_policy",
]
