from __future__ import annotations

from pathlib import Path


MIGRATION = Path(__file__).parents[1] / "migrations" / "0003_seed_mvp_access_control.sql"
REVOKED_LICENSE_MIGRATION = (
    Path(__file__).parents[1]
    / "migrations"
    / "0004_allow_unsigned_revoked_license.sql"
)

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


def test_tenant_role_has_explicit_data_plane_permissions_without_platform_identity_access() -> None:
    sql = _sql()
    for table in (
        "device.terminals", "device.devices", "subject.subjects", "subject.consents",
        "screening.sessions", "screening.session_segments", "screening.session_manifests",
        "ops.idempotency_keys", "ops.outbox_events",
    ):
        assert f" ON {table} TO ffp_tenant_app;" in sql
    for table in PLATFORM_TABLES:
        assert f" ON {table} TO ffp_tenant_app;" not in sql


def test_dynamic_bindings_keep_history_and_prevent_two_open_rows() -> None:
    sql = _sql()

    assert "CREATE UNIQUE INDEX uq_open_hardware_binding" in sql
    assert "WHERE unbound_at IS NULL" in sql
    assert "CREATE UNIQUE INDEX uq_open_license_assignment" in sql
    assert "WHERE unassigned_at IS NULL" in sql
    assert "CREATE UNIQUE INDEX uq_open_hardware_lease" in sql
    assert "WHERE released_at IS NULL" in sql


def test_unsigned_revoked_license_patch_is_transactional_and_idempotent() -> None:
    sql = REVOKED_LICENSE_MIGRATION.read_text(encoding="utf-8")

    assert sql.startswith("BEGIN;")
    assert sql.rstrip().endswith("COMMIT;")
    assert "license_entitlements_document_state_check" in sql
    assert "status = 'REVOKED'" in sql
    assert "pg_get_constraintdef" in sql
