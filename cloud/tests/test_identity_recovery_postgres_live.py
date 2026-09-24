"""Opt-in PostgreSQL role/RLS check for the controlled recovery path."""

from __future__ import annotations

import asyncio
import hashlib
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from cloud.api.errors import ResourceNotFound
from cloud.identity_recovery.postgres import PostgresRecoveryCaseRepository
from cloud.identity_recovery.service import IdentityRecoveryService
from cloud.ingestion.principal import IngestionPrincipal
from shared.contracts.identity_recovery import RecoveryCaseCreateRequest


_DSN_NAMES = (
    "FEETFORCEPLATE_TEST_ADMIN_DSN",
    "FEETFORCEPLATE_TEST_TENANT_DSN",
    "FEETFORCEPLATE_TEST_PLATFORM_DSN",
)


@pytest.mark.skipif(
    not all(os.environ.get(name) for name in _DSN_NAMES),
    reason="isolated PostgreSQL admin, tenant and platform DSNs are not configured",
)
def test_recovery_case_and_comparison_obey_live_roles_and_tenant_rls() -> None:
    async def exercise() -> None:
        import asyncpg

        tenant_id, other_tenant_id = uuid4(), uuid4()
        terminal_id, cloud_subject_id, original_subject_id = uuid4(), uuid4(), uuid4()
        identifier_id, session_id = uuid4(), uuid4()
        admin = await asyncpg.connect(os.environ[_DSN_NAMES[0]])
        tenant_pool = await asyncpg.create_pool(os.environ[_DSN_NAMES[1]], min_size=1, max_size=2)
        platform_pool = await asyncpg.create_pool(os.environ[_DSN_NAMES[2]], min_size=1, max_size=2)
        try:
            for value in (tenant_id, other_tenant_id):
                await admin.execute(
                    "INSERT INTO iam.tenants (tenant_id, name, status) VALUES ($1, 'RAY-99 test', 'ACTIVE')",
                    value,
                )
            await admin.execute(
                """INSERT INTO device.terminals
                   (terminal_id, tenant_id, installation_id, client_public_key, status)
                   VALUES ($1,$2,$3,'test-public-key','ACTIVE')""",
                terminal_id, tenant_id, uuid4(),
            )
            await admin.execute(
                "INSERT INTO subject.subjects (subject_uuid, tenant_id, status) VALUES ($1,$2,'ACTIVE')",
                cloud_subject_id, tenant_id,
            )
            await admin.execute(
                """INSERT INTO subject.external_identifiers
                   (external_identifier_id, tenant_id, subject_uuid, issuer, id_type,
                    encrypted_value, encryption_nonce, normalized_hmac, masked_value,
                    key_version, status)
                   VALUES ($1,$2,$3,'institution','record-number',$4,$5,$6,'***0731',
                           'test-key','ACTIVE')""",
                identifier_id, tenant_id, cloud_subject_id,
                b"synthetic-ciphertext", b"synthetic-nonce", hashlib.sha256(b"synthetic-0731").digest(),
            )
            principal = IngestionPrincipal(
                tenant_id=tenant_id, terminal_id=terminal_id,
                expires_at=datetime.now(UTC) + timedelta(minutes=10),
                allow_new_test=False, allow_upload=True,
            )
            repository = PostgresRecoveryCaseRepository(tenant_pool, platform_pool)
            service = IdentityRecoveryService(repository)
            request = RecoveryCaseCreateRequest(
                session_id=session_id, original_subject_uuid=original_subject_id,
                cloud_subject_uuid=cloud_subject_id, envelope_sha256="a" * 64,
                identifier_issuer="institution", identifier_type="record-number",
                external_identifier_id=identifier_id, terminal_id=terminal_id,
            )
            created = await service.create_case(principal, request, "live-case")
            assert created.status == "PENDING"
            assert (await service.create_case(principal, request, "live-case")).case_id == created.case_id
            other_principal = IngestionPrincipal(
                tenant_id=other_tenant_id, terminal_id=terminal_id,
                expires_at=principal.expires_at, allow_new_test=False, allow_upload=True,
            )
            with pytest.raises(ResourceNotFound):
                await service.get_case(other_principal, created.case_id)
            compared = await repository.record_comparison(
                tenant_id, created.case_id, matched=True,
                actor_id=uuid4(), grant_id=uuid4(),
                ticket_sha256=hashlib.sha256(b"synthetic-ticket").hexdigest(),
            )
            assert compared.decision == "MATCHED"
            assert (await service.get_case(principal, created.case_id)).receipt_id == compared.receipt_id
            assert await admin.fetchval(
                "SELECT count(*) FROM ops.identity_recovery_comparisons WHERE tenant_id=$1 AND case_id=$2",
                tenant_id, created.case_id,
            ) == 1
            second_request = request.model_copy(update={"session_id": uuid4()})
            second = await service.create_case(principal, second_request, "replaced-identifier-case")
            await admin.execute(
                "UPDATE subject.external_identifiers SET normalized_hmac=$1 WHERE external_identifier_id=$2",
                hashlib.sha256(b"changed-identifier").digest(), identifier_id,
            )
            with pytest.raises(ResourceNotFound):
                await repository.record_comparison(
                    tenant_id, second.case_id, matched=True,
                    actor_id=uuid4(), grant_id=uuid4(),
                    ticket_sha256=hashlib.sha256(b"another-ticket").hexdigest(),
                )
            assert (await repository.get_case(tenant_id, terminal_id, second.case_id)).attempts == 0
            assert await admin.fetchval(
                "SELECT count(*) FROM ops.identity_recovery_receipts WHERE tenant_id=$1 AND case_id=$2",
                tenant_id, second.case_id,
            ) == 0
            async with platform_pool.acquire() as connection:
                async with connection.transaction():
                    await connection.execute("SELECT set_config('app.tenant_id',$1,true)", str(tenant_id))
                    with pytest.raises(asyncpg.InsufficientPrivilegeError):
                        await connection.fetchval(
                            "SELECT encrypted_value FROM subject.external_identifiers LIMIT 1"
                        )
        finally:
            await platform_pool.close()
            await tenant_pool.close()
            await admin.close()

    asyncio.run(exercise())
