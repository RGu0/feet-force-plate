from __future__ import annotations

import asyncio
import os

import pytest


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
