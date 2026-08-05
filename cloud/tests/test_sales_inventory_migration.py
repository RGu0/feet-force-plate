from pathlib import Path


MIGRATION = (
    Path(__file__).parents[1] / "migrations" / "0006_inventory_activation_pairing.sql"
)


def test_inventory_migration_preserves_independent_pools_until_first_activation() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert sql.startswith("BEGIN;")
    assert sql.rstrip().endswith("COMMIT;")
    assert "ADD COLUMN activation_binding_mode" in sql
    assert "AT_FIRST_ACTIVATION" in sql
    assert "Never infer or pre-bind a device-to-code pair" in sql
    assert "device_inventory_id uuid REFERENCES" not in sql
    assert "GRANT SELECT, UPDATE ON sales.device_inventory, sales.license_inventory TO ffp_activation_app" in sql
