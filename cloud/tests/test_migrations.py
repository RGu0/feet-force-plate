from __future__ import annotations

from pathlib import Path


MIGRATION = Path(__file__).parents[1] / "migrations" / "0003_seed_mvp_access_control.sql"

TENANT_TABLES = (
    "iam.tenant_accounts",
    "iam.account_activation_codes",
    "iam.tenant_refresh_sessions",
    "device.hardware_assets",
    "device.license_entitlements",
    "device.license_assignments",
    "device.hardware_bindings",
    "device.client_installations",
    "device.hardware_leases",
    "ops.sensitive_access_grants",
)

PLATFORM_TABLES = (
    "iam.platform_identities",
    "iam.platform_roles",
    "iam.platform_identity_role_bindings",
    "iam.platform_refresh_sessions",
)


def _sql() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def test_seed_access_migration_is_additive_and_transactional() -> None:
    sql = _sql()

    assert sql.startswith("BEGIN;")
    assert sql.rstrip().endswith("COMMIT;")
    assert "ALTER TABLE device.licenses" not in sql
    assert "DROP TABLE" not in sql


def test_authoritative_tables_exist() -> None:
    sql = _sql()

    for table in TENANT_TABLES + PLATFORM_TABLES + ("ops.authentication_attempts",):
        assert f"CREATE TABLE {table}" in sql


def test_tenant_tables_force_row_level_security() -> None:
    sql = _sql()

    for table in TENANT_TABLES:
        assert f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;" in sql
        assert f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;" in sql
        policy_name = table.replace(".", "_") + "_tenant_isolation"
        assert f"CREATE POLICY {policy_name} ON {table}" in sql


def test_platform_tables_are_not_tenant_rls_tables() -> None:
    sql = _sql()

    for table in PLATFORM_TABLES:
        assert f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY" not in sql
        assert f"GRANT SELECT, INSERT, UPDATE ON {table} TO ffp_platform_app;" in sql
        assert " TO ffp_tenant_app;" not in "\n".join(
            line for line in sql.splitlines() if table in line
        )


def test_application_roles_are_explicitly_non_privileged() -> None:
    sql = _sql()

    for role in ("ffp_tenant_app", "ffp_activation_app", "ffp_platform_app"):
        assert f"CREATE ROLE {role} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS" in sql
    assert " BYPASSRLS" not in sql.replace("NOBYPASSRLS", "")


def test_dynamic_bindings_keep_history_and_prevent_two_open_rows() -> None:
    sql = _sql()

    assert "CREATE UNIQUE INDEX uq_open_hardware_binding" in sql
    assert "WHERE unbound_at IS NULL" in sql
    assert "CREATE UNIQUE INDEX uq_open_license_assignment" in sql
    assert "WHERE unassigned_at IS NULL" in sql
    assert "CREATE UNIQUE INDEX uq_open_hardware_lease" in sql
    assert "WHERE released_at IS NULL" in sql
