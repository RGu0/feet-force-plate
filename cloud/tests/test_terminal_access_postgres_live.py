"""RAY-656 terminal persistence parity against live PostgreSQL role pools."""

from __future__ import annotations

import asyncio
import hashlib
import os
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from cloud.access_control.postgres import PostgresAccessRepository
from cloud.access_control.repository import (
    InMemoryAccessRepository,
    TenantSeed,
    TerminalInstallationOwned,
    TerminalRecord,
    TerminalRefreshRace,
    TerminalRefreshSessionRecord,
    TerminalSeatsExhausted,
)
from cloud.tests.test_postgres_access_repository import NOW, _group, _live_dsns


ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "cloud/migrations/0012_terminal_activation.sql"


def test_migration_is_additive_rls_scoped_and_least_privilege() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    assert sql.startswith("BEGIN;") and sql.rstrip().endswith("COMMIT;")
    assert "DROP TABLE" not in sql
    assert "ADD COLUMN terminal_seats integer NOT NULL DEFAULT 0" in sql
    for table in ("iam.access_terminals", "iam.terminal_refresh_sessions"):
        assert f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;" in sql
        assert f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;" in sql
    for directory in ("iam.terminal_directory", "iam.terminal_refresh_directory"):
        assert f"REVOKE ALL ON {directory} FROM PUBLIC;" in sql
    assert "TO ffp_tenant_app" not in sql
    assert "'TERMINAL_ACTIVATION'" in sql


def test_deployment_applies_and_backs_up_terminal_migration() -> None:
    install = (ROOT / "deploy/aliyun/seed/install-seed-release.sh").read_text(encoding="utf-8")
    backup = (ROOT / "deploy/aliyun/seed/backup.sh").read_text(encoding="utf-8")
    assert install.index("0012_terminal_activation.sql") > install.index(
        "0011_controlled_identity_recovery.sql"
    )
    assert "iam.terminal_refresh_directory\n     TO ffp_seed_backup" in install
    assert "0011_controlled_identity_recovery,0012_terminal_activation" in backup


def _terminal(tenant_id, group, *, installation=None) -> TerminalRecord:
    return TerminalRecord(
        tenant_id=tenant_id, client_installation_id=installation or uuid4(),
        account_id=group.account_id, license_id=group.license_id,
        terminal_name="Front desk", platform="ios", status="ACTIVE",
        refresh_family_id=uuid4(), activated_at=NOW,
    )


def _session(terminal: TerminalRecord, *, at=NOW) -> TerminalRefreshSessionRecord:
    return TerminalRefreshSessionRecord(
        refresh_session_id=uuid4(), tenant_id=terminal.tenant_id,
        account_id=terminal.account_id,
        client_installation_id=terminal.client_installation_id,
        refresh_family_id=terminal.refresh_family_id,
        refresh_token_hash=hashlib.sha256(os.urandom(32)).digest(),
        issued_at=at, idle_expires_at=at + timedelta(days=30),
        absolute_expires_at=NOW + timedelta(days=180),
    )


async def _exercise(repository) -> None:
    tenant = TenantSeed(uuid4(), f"Terminal parity {uuid4()}")
    other = TenantSeed(uuid4(), f"Terminal parity other {uuid4()}")
    nonce = os.urandom(32)
    group, other_group = _group(21, run_nonce=nonce), _group(22, run_nonce=nonce)
    await repository.provision_tenant(tenant, group, created_at=NOW)
    await repository.provision_tenant(other, other_group, created_at=NOW)
    seats = await repository.set_terminal_seats(
        license_id=group.license_id, seats=1, changed_at=NOW
    )
    assert seats.terminal_seats == 1
    assert (await repository.license(group.license_id)).terminal_seats == 1

    first = _terminal(tenant.tenant_id, group)
    first_session = _session(first)
    await repository.activate_terminal_atomically(terminal=first, session=first_session)
    second = _terminal(tenant.tenant_id, group)
    with pytest.raises(TerminalSeatsExhausted):
        await repository.activate_terminal_atomically(terminal=second, session=_session(second))
    await repository.set_terminal_seats(
        license_id=other_group.license_id, seats=1, changed_at=NOW
    )
    foreign = _terminal(other.tenant_id, other_group, installation=first.client_installation_id)
    with pytest.raises(TerminalInstallationOwned):
        await repository.activate_terminal_atomically(terminal=foreign, session=_session(foreign))

    assert (await repository.terminal_refresh_by_hash(first_session.refresh_token_hash)) == first_session
    rotated_at = NOW + timedelta(minutes=1)
    replacement = _session(first, at=rotated_at)
    await repository.rotate_terminal_refresh(
        current_token_hash=first_session.refresh_token_hash,
        replacement=replacement, rotated_at=rotated_at,
    )
    with pytest.raises(TerminalRefreshRace):
        await repository.rotate_terminal_refresh(
            current_token_hash=first_session.refresh_token_hash,
            replacement=_session(first, at=rotated_at), rotated_at=rotated_at,
        )
    retired = await repository.terminal_refresh_by_hash(first_session.refresh_token_hash)
    assert retired.rotated_at == rotated_at
    assert retired.replaced_by_session_id == replacement.refresh_session_id
    assert (await repository.terminal(first.client_installation_id)).last_refreshed_at == rotated_at

    await repository.revoke_terminal_refresh_family(
        tenant_id=tenant.tenant_id, refresh_family_id=first.refresh_family_id,
        reason="REFRESH_REPLAYED", revoked_at=rotated_at,
    )
    successor = await repository.terminal_refresh_session(
        tenant_id=tenant.tenant_id, refresh_session_id=replacement.refresh_session_id
    )
    assert successor.revoke_reason == "REFRESH_REPLAYED"

    renamed = await repository.rename_terminal(
        tenant_id=tenant.tenant_id, account_id=group.account_id,
        client_installation_id=first.client_installation_id, terminal_name="Gait lab",
    )
    assert renamed.terminal_name == "Gait lab"
    revoked = await repository.revoke_terminal(
        tenant_id=tenant.tenant_id, account_id=group.account_id,
        client_installation_id=first.client_installation_id, revoked_at=rotated_at,
    )
    assert (revoked.status, revoked.revoked_at) == ("REVOKED", rotated_at)
    # The released seat admits another terminal; the revoked one can return.
    await repository.activate_terminal_atomically(terminal=second, session=_session(second))
    listed = await repository.terminals_for_account(
        tenant_id=tenant.tenant_id, account_id=group.account_id
    )
    assert {row.status for row in listed} == {"ACTIVE", "REVOKED"}


def test_in_memory_repository_satisfies_the_same_lifecycle() -> None:
    asyncio.run(_exercise(InMemoryAccessRepository()))


@pytest.mark.skipif(_live_dsns() is None, reason="three PostgreSQL role DSNs are not configured")
def test_live_terminal_repository_parity() -> None:
    async def exercise() -> None:
        import asyncpg

        tenant_dsn, activation_dsn, platform_dsn = _live_dsns() or ("", "", "")
        pools = [
            await asyncpg.create_pool(dsn, min_size=1, max_size=3)
            for dsn in (tenant_dsn, activation_dsn, platform_dsn)
        ]
        try:
            await _exercise(
                PostgresAccessRepository(
                    tenant_pool=pools[0], activation_pool=pools[1], platform_pool=pools[2]
                )
            )
        finally:
            for pool in pools:
                await pool.close()

    asyncio.run(exercise())
