from __future__ import annotations

import base64
import unittest
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from client.cloud.policy import (
    AccountHardwareLicenseVerifier,
    HardwareLeaseSnapshot,
    PolicyConnectivity,
    PolicyEvidence,
    SeedLicensePolicyInput,
    evaluate_seed_license_policy,
)
from client.spool.state_store import OFFLINE_LIMIT_NS, OfflineSnapshot
from shared.contracts.access_control import LicenseDocumentV2, LicenseState, SignedLicenseV2
from shared.contracts.client_sync import canonical_json_bytes
from shared.contracts.device_policy import GateReason


class SeedLicensePolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
        self.tenant_id = uuid4()
        self.account_id = uuid4()
        self.license_id = uuid4()
        self.installation_id = uuid4()
        self.hardware_id = "usb-serial-0123456789abcdef0123"
        self.private_key = Ed25519PrivateKey.generate()
        public = self.private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        self.verifier = AccountHardwareLicenseVerifier({"license/2-key-1": public})

    def document(self, **updates) -> LicenseDocumentV2:
        values = {
            "tenant_id": self.tenant_id,
            "account_id": self.account_id,
            "license_id": self.license_id,
            "hardware_id": self.hardware_id,
            "status": LicenseState.ACTIVE,
            "issued_at": self.now - timedelta(days=1),
            "valid_from": self.now - timedelta(days=1),
            "valid_until": self.now + timedelta(days=365),
            "version": 3,
            "enabled_features": (
                "reports.view",
                "screening.start",
                "sync.upload",
            ),
        }
        values.update(updates)
        return LicenseDocumentV2.model_validate(values)

    def signed(self, document: LicenseDocumentV2) -> SignedLicenseV2:
        signature = self.private_key.sign(canonical_json_bytes(document))
        return SignedLicenseV2(
            document=document,
            key_id="license/2-key-1",
            signature=base64.b64encode(signature).decode("ascii"),
        )

    def state(self, **updates) -> SeedLicensePolicyInput:
        values = {
            "evaluated_at": self.now,
            "monotonic_now_ns": OFFLINE_LIMIT_NS,
            "connectivity": PolicyConnectivity.ONLINE,
            "clock_trusted": True,
            "offline": OfflineSnapshot(0, 0, 0),
            "client_installation_id": self.installation_id,
            "lease": HardwareLeaseSnapshot(
                self.installation_id,
                self.now + timedelta(minutes=10),
            ),
        }
        values.update(updates)
        return SeedLicensePolicyInput(**values)

    def test_license2_signature_binding_and_monotonic_version(self) -> None:
        bundle = self.signed(self.document())
        verified = self.verifier.verify(
            bundle,
            expected_tenant_id=self.tenant_id,
            expected_account_id=self.account_id,
            expected_license_id=self.license_id,
            expected_hardware_id=self.hardware_id,
            minimum_version=3,
        )
        self.assertEqual(verified.version, 3)

        with self.assertRaisesRegex(ValueError, "downgrade"):
            self.verifier.verify(
                self.signed(self.document(version=2)),
                expected_tenant_id=self.tenant_id,
                expected_account_id=self.account_id,
                expected_license_id=self.license_id,
                expected_hardware_id=self.hardware_id,
                minimum_version=3,
            )
        with self.assertRaisesRegex(ValueError, "binding"):
            self.verifier.verify(
                bundle,
                expected_tenant_id=self.tenant_id,
                expected_account_id=self.account_id,
                expected_license_id=self.license_id,
                expected_hardware_id="usb-serial-ffffffffffffffffffff",
            )

    def test_active_online_requires_current_installation_lease(self) -> None:
        allowed = evaluate_seed_license_policy(self.document(), self.state())
        missing = evaluate_seed_license_policy(
            self.document(), self.state(lease=None)
        )
        conflict = evaluate_seed_license_policy(
            self.document(),
            self.state(
                lease=HardwareLeaseSnapshot(uuid4(), self.now + timedelta(minutes=10))
            ),
        )

        self.assertTrue(allowed.allow_new_test)
        self.assertEqual(allowed.evidence, PolicyEvidence.ONLINE_LEASE_PROVEN)
        self.assertIn(GateReason.LEASE_REQUIRED, missing.reasons)
        self.assertIn(GateReason.LEASE_CONFLICT, conflict.reasons)

    def test_offline_grace_allows_exact_24h_but_states_exclusivity_limit(self) -> None:
        exact = evaluate_seed_license_policy(
            self.document(),
            self.state(
                connectivity=PolicyConnectivity.OFFLINE,
                lease=None,
                monotonic_now_ns=OFFLINE_LIMIT_NS,
            ),
        )
        exceeded = evaluate_seed_license_policy(
            self.document(),
            self.state(
                connectivity=PolicyConnectivity.OFFLINE,
                lease=None,
                monotonic_now_ns=OFFLINE_LIMIT_NS + 1,
            ),
        )

        self.assertTrue(exact.allow_new_test)
        self.assertEqual(
            exact.evidence,
            PolicyEvidence.OFFLINE_GRACE_NO_GLOBAL_LEASE_PROOF,
        )
        self.assertFalse(exceeded.allow_new_test)
        self.assertIn(GateReason.OFFLINE_TOO_LONG, exceeded.reasons)

    def test_license_states_clock_and_spool_quotas_only_block_new_tests(self) -> None:
        cases = (
            (self.document(status=LicenseState.SUSPENDED), self.state(), GateReason.LICENSE_SUSPENDED),
            (self.document(status=LicenseState.REVOKED), self.state(), GateReason.LICENSE_REVOKED),
            (
                self.document(valid_until=self.now),
                self.state(),
                GateReason.LICENSE_EXPIRED,
            ),
            (self.document(), self.state(clock_trusted=False), GateReason.CLOCK_ROLLBACK),
            (
                self.document(),
                self.state(offline=OfflineSnapshot(0, 50, 0)),
                GateReason.PENDING_SESSION_LIMIT,
            ),
            (
                self.document(),
                self.state(offline=OfflineSnapshot(0, 0, 2 * 1024**3)),
                GateReason.PENDING_BYTES_LIMIT,
            ),
        )
        for document, state, reason in cases:
            with self.subTest(reason=reason):
                decision = evaluate_seed_license_policy(document, state)
                self.assertFalse(decision.allow_new_test)
                self.assertIn(reason, decision.reasons)
                self.assertTrue(decision.allow_finalize_current_test)
                self.assertTrue(decision.allow_report_view)
                self.assertTrue(decision.allow_upload)


if __name__ == "__main__":
    unittest.main()
