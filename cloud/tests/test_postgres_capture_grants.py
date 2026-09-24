from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import hashlib
import os
from uuid import uuid4

import pytest

from cloud.access_control.postgres import PostgresAccessRepository
from cloud.access_control.repository import (
    AccessGroupSeed,
    PlatformIdentityRecord,
    PlatformRoleBindingRecord,
    TenantSeed,
)
from cloud.api.postgres import tenant_transaction
from shared.contracts.access_control import PlatformRole


NOW = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)


def _group() -> AccessGroupSeed:
    nonce = os.urandom(32)
    return AccessGroupSeed(
        account_id=uuid4(),
        login_name_hmac=hashlib.sha256(b"login" + nonce).digest(),
        account_display_name=f"capture-grant-test-{nonce.hex()[:8]}",
        license_id=uuid4(),
        hardware_id=uuid4(),
        hardware_identity=f"usb-serial-{hashlib.sha256(nonce).hexdigest()[:20]}",
        hardware_model="DO-P4864",
        activation_code_id=uuid4(),
        activation_code_hash=hashlib.sha256(b"activation" + nonce).digest(),
        activation_expires_at=NOW + timedelta(days=7),
        license_valid_from=NOW,
        license_valid_until=NOW + timedelta(days=365),
        enabled_features=("reports.view", "screening.start", "sync.upload"),
    )


def _role_dsns() -> tuple[str, str, str] | None:
    names = (
        "FEETFORCEPLATE_TEST_TENANT_DSN",
        "FEETFORCEPLATE_TEST_ACTIVATION_DSN",
        "FEETFORCEPLATE_TEST_PLATFORM_DSN",
    )
    values = tuple(os.environ.get(name, "") for name in names)
    return values if all(values) else None


@pytest.mark.skipif(_role_dsns() is None, reason="three PostgreSQL role DSNs are not configured")
def test_live_capture_authorization_role_and_rls_contract() -> None:
    async def exercise() -> None:
        import asyncpg

        tenant_dsn, activation_dsn, platform_dsn = _role_dsns() or ("", "", "")
        tenant = await asyncpg.connect(tenant_dsn)
        activation = await asyncpg.connect(activation_dsn)
        platform = await asyncpg.connect(platform_dsn)
        try:
            for table in (
                "screening.capture_grants",
                "screening.upload_migration_permits",
                "ops.capture_authorization_audit",
            ):
                row = await tenant.fetchrow(
                    "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE oid=$1::regclass",
                    table,
                )
                assert tuple(row.values()) == (True, True)
                assert not await activation.fetchval(
                    "SELECT has_table_privilege(current_user, $1, 'SELECT')", table
                )
                assert not await tenant.fetchval(
                    """SELECT EXISTS (
                           SELECT 1 FROM aclexplode(relacl)
                           WHERE grantee=0 AND privilege_type='SELECT'
                       ) FROM pg_class WHERE oid=$1::regclass""",
                    table,
                )
            assert await tenant.fetchval(
                "SELECT has_table_privilege(current_user, 'screening.capture_grants', 'INSERT')"
            )
            assert not await tenant.fetchval(
                "SELECT has_table_privilege(current_user, 'screening.upload_migration_permits', 'INSERT')"
            )
            assert await platform.fetchval(
                "SELECT has_table_privilege(current_user, 'screening.upload_migration_permits', 'INSERT')"
            )
        finally:
            await tenant.close()
            await activation.close()
            await platform.close()

    asyncio.run(exercise())


@pytest.mark.skipif(_role_dsns() is None, reason="three PostgreSQL role DSNs are not configured")
def test_live_capture_authorization_operations_are_tenant_scoped_and_one_way() -> None:
    async def exercise() -> None:
        import asyncpg

        tenant_dsn, activation_dsn, platform_dsn = _role_dsns() or ("", "", "")
        tenant_pool = await asyncpg.create_pool(tenant_dsn, min_size=1, max_size=2)
        activation_pool = await asyncpg.create_pool(activation_dsn, min_size=1, max_size=2)
        platform_pool = await asyncpg.create_pool(platform_dsn, min_size=1, max_size=2)
        repository = PostgresAccessRepository(
            tenant_pool=tenant_pool,
            activation_pool=activation_pool,
            platform_pool=platform_pool,
        )
        first, second = (TenantSeed(uuid4(), f"Capture grant test {uuid4()}") for _ in range(2))
        first_group, second_group = _group(), _group()
        first_installation_id, second_installation_id = uuid4(), uuid4()
        grant_session_id, permit_session_id = uuid4(), uuid4()
        request_digest, manifest_digest = "a" * 64, "b" * 64
        try:
            for tenant, group, installation_id in (
                (first, first_group, first_installation_id),
                (second, second_group, second_installation_id),
            ):
                await repository.provision_tenant(tenant, group, created_at=NOW)
                activated = await repository.activate_account_atomically(
                    login_name_hmac=group.login_name_hmac,
                    activation_code_hash=group.activation_code_hash,
                    hardware_identity=group.hardware_identity,
                    password_hash="$ffp-scrypt$capture-test",
                    installation_id=installation_id,
                    activated_at=NOW + timedelta(minutes=1),
                    license_key_id="license/2-test",
                    license_document_json='{"schema_version":"license/2"}',
                    license_signature="s" * 86,
                )
                assert activated.installation.client_installation_id == installation_id

            async with tenant_transaction(tenant_pool, first.tenant_id) as connection:
                await connection.execute(
                    """INSERT INTO screening.capture_grants
                       (tenant_id,session_id,installation_id,account_id,license_id,
                        hardware_id,token_sha256)
                       VALUES ($1,$2,$3,$4,$5,$6,$7)""",
                    first.tenant_id, grant_session_id, first_installation_id,
                    first_group.account_id, first_group.license_id,
                    first_group.hardware_id, os.urandom(32),
                )
                assert await connection.fetchval(
                    "SELECT state FROM screening.capture_grants WHERE session_id=$1",
                    grant_session_id,
                ) == "ISSUED"
                await connection.execute(
                    """UPDATE screening.capture_grants
                       SET state='CONSUMED',consumed_request_sha256=$3,
                           expected_manifest_sha256=$4
                       WHERE tenant_id=$1 AND session_id=$2""",
                    first.tenant_id, grant_session_id, request_digest, manifest_digest,
                )
                assert await connection.fetchval(
                    "SELECT state FROM screening.capture_grants WHERE session_id=$1",
                    grant_session_id,
                ) == "CONSUMED"

                with pytest.raises(asyncpg.PostgresError):
                    async with connection.transaction():
                        await connection.execute(
                            """UPDATE screening.capture_grants
                               SET expected_manifest_sha256=$3
                               WHERE tenant_id=$1 AND session_id=$2""",
                            first.tenant_id, grant_session_id, "c" * 64,
                        )
                with pytest.raises(asyncpg.PostgresError):
                    async with connection.transaction():
                        await connection.execute(
                            """UPDATE screening.capture_grants SET state='ISSUED'
                               WHERE tenant_id=$1 AND session_id=$2""",
                            first.tenant_id, grant_session_id,
                        )
                with pytest.raises(asyncpg.InsufficientPrivilegeError):
                    async with connection.transaction():
                        await connection.execute(
                            """UPDATE screening.capture_grants SET account_id=$3
                               WHERE tenant_id=$1 AND session_id=$2""",
                            first.tenant_id, grant_session_id, second_group.account_id,
                        )

            async with tenant_transaction(tenant_pool, second.tenant_id) as connection:
                assert await connection.fetchval(
                    "SELECT count(*) FROM screening.capture_grants WHERE session_id=$1",
                    grant_session_id,
                ) == 0
                with pytest.raises(asyncpg.InsufficientPrivilegeError):
                    async with connection.transaction():
                        await connection.execute(
                            """INSERT INTO screening.capture_grants
                               (tenant_id,session_id,installation_id,account_id,license_id,
                                hardware_id,token_sha256)
                               VALUES ($1,$2,$3,$4,$5,$6,$7)""",
                            first.tenant_id, uuid4(), first_installation_id,
                            first_group.account_id, first_group.license_id,
                            first_group.hardware_id, os.urandom(32),
                        )
                assert await connection.fetchval(
                    """UPDATE screening.capture_grants SET state='RETIRED'
                       WHERE tenant_id=$1 AND session_id=$2 RETURNING session_id""",
                    first.tenant_id, grant_session_id,
                ) is None

            approver = PlatformIdentityRecord(
                platform_identity_id=uuid4(), login_name_hmac=os.urandom(32),
                display_name="Capture Permit Test Owner",
                password_hash="$ffp-scrypt$platform", status="ACTIVE",
                token_version=1, created_at=NOW,
            )
            await repository.create_platform_identity(
                approver,
                (PlatformRoleBindingRecord(
                    uuid4(), approver.platform_identity_id, PlatformRole.OWNER, NOW,
                ),),
            )
            permit_args = (
                first.tenant_id, permit_session_id, first_installation_id,
                first_group.account_id, first_group.license_id,
                first_group.hardware_id, os.urandom(32), request_digest,
                manifest_digest, approver.platform_identity_id,
                "Reviewed legacy valid capture", "evidence/ray-513/test",
            )
            permit_sql = """INSERT INTO screening.upload_migration_permits
                (tenant_id,session_id,installation_id,account_id,license_id,
                 hardware_id,token_sha256,consumed_request_sha256,
                 expected_manifest_sha256,approver_id,approval_reason,evidence_reference)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)"""
            async with tenant_transaction(tenant_pool, first.tenant_id) as connection:
                with pytest.raises(asyncpg.InsufficientPrivilegeError):
                    async with connection.transaction():
                        await connection.execute(permit_sql, *permit_args)
            async with tenant_transaction(platform_pool, first.tenant_id) as connection:
                await connection.execute(permit_sql, *permit_args)
                assert await connection.fetchval(
                    "SELECT state FROM screening.upload_migration_permits WHERE session_id=$1",
                    permit_session_id,
                ) == "ISSUED"
            async with tenant_transaction(platform_pool, second.tenant_id) as connection:
                with pytest.raises(asyncpg.InsufficientPrivilegeError):
                    async with connection.transaction():
                        await connection.execute(
                            permit_sql,
                            first.tenant_id, uuid4(), *permit_args[2:6],
                            os.urandom(32), *permit_args[7:],
                        )
            async with tenant_transaction(tenant_pool, first.tenant_id) as connection:
                await connection.execute(
                    """UPDATE screening.upload_migration_permits SET state='CONSUMED'
                       WHERE tenant_id=$1 AND session_id=$2""",
                    first.tenant_id, permit_session_id,
                )
                with pytest.raises(asyncpg.PostgresError):
                    async with connection.transaction():
                        await connection.execute(
                            """UPDATE screening.upload_migration_permits SET state='ISSUED'
                               WHERE tenant_id=$1 AND session_id=$2""",
                            first.tenant_id, permit_session_id,
                        )
            async with tenant_transaction(tenant_pool, second.tenant_id) as connection:
                assert await connection.fetchval(
                    "SELECT count(*) FROM screening.upload_migration_permits WHERE session_id=$1",
                    permit_session_id,
                ) == 0
        finally:
            await tenant_pool.close()
            await activation_pool.close()
            await platform_pool.close()

    asyncio.run(exercise())
