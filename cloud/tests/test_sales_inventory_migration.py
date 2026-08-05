from pathlib import Path


MIGRATION = (
    Path(__file__).parents[1] / "migrations" / "0006_inventory_activation_pairing.sql"
)


def test_inventory_pairing_migration_requires_an_audited_legacy_import() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert sql.startswith("BEGIN;")
    assert sql.rstrip().endswith("COMMIT;")
    assert "ADD COLUMN device_inventory_id" in sql
    assert "UNIQUE (device_inventory_id)" in sql
    assert "existing sales inventory requires an audited device-to-code import" in sql
    assert "GRANT SELECT, UPDATE ON sales.device_inventory, sales.license_inventory TO ffp_activation_app" in sql
