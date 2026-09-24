from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from pydantic import ValidationError
from httpx import ASGITransport, AsyncClient

from cloud.api.errors import IdempotencyConflict, ResourceNotFound, TenantAccessDenied
from cloud.api.app import ServiceContainer, create_app
from cloud.api.auth import TerminalTokenIssuer
from cloud.ingestion.principal import IngestionPrincipal
from cloud.identity_recovery.repository import InMemoryRecoveryCaseRepository
from cloud.identity_recovery.service import IdentityRecoveryService
from shared.contracts.identity_recovery import RecoveryCaseCreateRequest


class RecoveryCaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tenant, self.terminal, self.cloud_subject = uuid4(), uuid4(), uuid4()
        self.principal = IngestionPrincipal(
            tenant_id=self.tenant, terminal_id=self.terminal,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            allow_new_test=False, allow_upload=True,
        )
        self.repository = InMemoryRecoveryCaseRepository()
        self.repository.add_subject(self.tenant, self.cloud_subject, masked_clue="***0731")
        self.service = IdentityRecoveryService(self.repository)
        self.request = RecoveryCaseCreateRequest(
            session_id=uuid4(), original_subject_uuid=uuid4(),
            cloud_subject_uuid=self.cloud_subject, envelope_sha256="a" * 64,
            identifier_issuer="institution", identifier_type="record-number",
            terminal_id=self.terminal,
        )

    async def test_immutable_retry_and_changed_key_conflict(self) -> None:
        first = await self.service.create_case(self.principal, self.request, "case-1")
        self.assertEqual(first, await self.service.create_case(self.principal, self.request, "case-1"))
        self.assertEqual(first, await self.service.get_case(self.principal, first.case_id))
        self.assertEqual(first.status, "PENDING")
        self.assertEqual(first.masked_clue, "***0731")
        self.assertNotIn("display_name", first.model_dump())
        with self.assertRaises(IdempotencyConflict):
            await self.service.create_case(
                self.principal, self.request.model_copy(update={"envelope_sha256": "b" * 64}), "case-1"
            )
        with self.assertRaises(IdempotencyConflict):
            await self.service.create_case(
                self.principal, self.request.model_copy(update={"envelope_sha256": "b" * 64}), "case-2"
            )

    async def test_context_and_subject_binding(self) -> None:
        with self.assertRaises(TenantAccessDenied):
            await self.service.create_case(
                self.principal, self.request.model_copy(update={"terminal_id": uuid4()}), "different-terminal"
            )
        with self.assertRaises(ResourceNotFound):
            await self.service.create_case(
                self.principal, self.request.model_copy(update={"cloud_subject_uuid": uuid4()}), "missing-subject"
            )
        other = self.principal.__class__(
            tenant_id=uuid4(), terminal_id=self.terminal, expires_at=self.principal.expires_at,
            allow_new_test=False, allow_upload=True,
        )
        created = await self.service.create_case(self.principal, self.request, "case-1")
        with self.assertRaises(ResourceNotFound):
            await self.service.get_case(other, created.case_id)

    def test_rejects_malformed_or_self_mapping(self) -> None:
        with self.assertRaises(ValidationError):
            RecoveryCaseCreateRequest.model_validate(
                {**self.request.model_dump(), "envelope_sha256": "not-a-digest"}
            )
        with self.assertRaises(ValidationError):
            RecoveryCaseCreateRequest.model_validate(
                {**self.request.model_dump(), "original_subject_uuid": self.cloud_subject}
            )

    async def test_terminal_routes_bind_authentication_and_return_safe_summary(self) -> None:
        issuer = TerminalTokenIssuer(
            secret=b"test-only-recovery-token-secret-32-bytes", key_id="test-key",
            token_ttl=timedelta(minutes=10),
        )
        app = create_app(ServiceContainer(token_issuer=issuer, identity_recovery=self.service))
        headers = {
            "Authorization": f"Bearer {issuer.issue(self.tenant, self.terminal)}",
            "X-Terminal-ID": str(self.terminal), "Idempotency-Key": "route-1",
        }
        async with AsyncClient(transport=ASGITransport(app=app), base_url="https://cloud.test") as client:
            response = await client.post(
                "/v1/identity-recovery/cases", json=self.request.model_dump(mode="json"), headers=headers,
            )
            self.assertEqual(response.status_code, 201)
            case = response.json()["data"]
            self.assertEqual(case["status"], "PENDING")
            self.assertNotIn("display_name", str(response.json()))
            read = await client.get(f"/v1/identity-recovery/cases/{case['case_id']}", headers=headers)
            self.assertEqual(read.status_code, 200)
            self.assertEqual(read.json()["data"], case)
            wrong = await client.get(
                f"/v1/identity-recovery/cases/{case['case_id']}",
                headers={**headers, "Authorization": f"Bearer {issuer.issue(uuid4(), self.terminal)}"},
            )
            self.assertEqual(wrong.status_code, 404)
