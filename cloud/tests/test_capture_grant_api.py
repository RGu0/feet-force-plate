from dataclasses import replace
import asyncio
import hashlib
from uuid import UUID

from cloud.tests.test_tenant_access_ingestion import TenantAccessIngestionTests
from shared.contracts.access_control import LicenseControlAction, LicenseControlRequest


class CaptureGrantApiTests(TenantAccessIngestionTests):
    async def issue(self, count=1):
        return await self.client.post(
            "/v1/access/capture-grants", headers=self.headers(self.session.access_token),
            json={"count": count},
        )

    async def retire(self, session_id):
        return await self.client.post(
            "/v1/access/capture-grants/retire", headers=self.headers(self.session.access_token),
            json={"session_id": session_id, "reason": "CANCELED"},
        )

    async def test_issue_cap_retire_and_secret_storage(self):
        response = await self.issue(50)
        self.assertEqual(response.status_code, 201, response.text)
        grants = response.json()["data"]["grants"]
        self.assertEqual(len({g["session_id"] for g in grants}), 50)
        self.assertEqual(len({g["token"] for g in grants}), 50)
        self.assertEqual((await self.issue()).status_code, 403)
        for grant in grants:
            self.assertGreaterEqual(len(grant["token"]), 32)
            self.assertNotIn(grant["token"], repr(self.data_repository._capture_grants))
            self.assertNotIn(grant["token"], repr(self.data_repository._capture_audits))
            stored = self.data_repository._capture_grants[(self.provisioned.tenant_id, UUID(grant["session_id"]))]
            self.assertEqual(stored.token_sha256, hashlib.sha256(grant["token"].encode()).digest())
            self.assertEqual(stored.hardware_id, self.device_id)
        self.assertEqual((await self.retire(grants[0]["session_id"])).status_code, 200)
        self.assertEqual((await self.retire(grants[0]["session_id"])).status_code, 403)
        self.assertEqual(len((await self.issue(50)).json()["data"]["grants"]), 1)

    async def test_live_suspension_denies_stale_active_token_without_mutation(self):
        grant = (await self.issue()).json()["data"]["grants"][0]
        await self.platform.control_license(
            self.operator, self.provisioned.license_id,
            LicenseControlRequest(action=LicenseControlAction.SUSPEND, reason_code="CUSTOMER_REQUEST"),
        )
        self.assertEqual((await self.issue()).status_code, 403)
        self.assertEqual((await self.retire(grant["session_id"])).status_code, 403)
        self.assertEqual(len(self.data_repository._capture_grants), 1)
        await self.platform.control_license(
            self.operator, self.provisioned.license_id,
            LicenseControlRequest(action=LicenseControlAction.RESTORE, reason_code="CUSTOMER_REQUEST"),
        )
        self.assertEqual((await self.retire(grant["session_id"])).status_code, 200)
        self.assertEqual((await self.issue()).status_code, 201)

    async def test_consumed_grant_cannot_retire(self):
        grant = (await self.issue()).json()["data"]["grants"][0]
        key = next(iter(self.data_repository._capture_grants))
        self.data_repository._capture_grants[key] = replace(
            self.data_repository._capture_grants[key], state="CONSUMED"
        )
        self.assertEqual((await self.retire(grant["session_id"])).status_code, 403)

    async def test_concurrent_last_slot_has_one_winner(self):
        self.assertEqual((await self.issue(49)).status_code, 201)
        results = await asyncio.gather(self.issue(), self.issue())
        self.assertEqual(sorted(response.status_code for response in results), [201, 403])
        self.assertEqual(len(self.data_repository._capture_grants), 50)

    async def test_revoked_installation_and_wrong_hardware_denied(self):
        installation = self.access_repository._installations[self.installation_id]
        self.access_repository._installations[self.installation_id] = replace(installation, status="REVOKED")
        self.assertEqual((await self.issue()).status_code, 403)
        self.access_repository._installations[self.installation_id] = installation
        hardware = self.access_repository._hardware[self.device_id]
        self.access_repository._hardware[self.device_id] = replace(hardware, status="RETIRED")
        self.assertEqual((await self.issue()).status_code, 403)
        self.assertEqual(len(self.data_repository._capture_grants), 0)
