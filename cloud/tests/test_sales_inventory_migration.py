from pathlib import Path


MIGRATION = (
    Path(__file__).parents[1] / "migrations" / "0006_inventory_activation_pairing.sql"
)
POSTGRES_REPOSITORY = Path(__file__).parents[1] / "access_control" / "postgres.py"


def test_inventory_migration_preserves_independent_pools_until_first_activation() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert sql.startswith("BEGIN;")
    assert sql.rstrip().endswith("COMMIT;")
    assert "ADD COLUMN activation_binding_mode" in sql
    assert "AT_FIRST_ACTIVATION" in sql
    assert "Never infer or pre-bind a device-to-code pair" in sql
    assert "device_inventory_id uuid REFERENCES" not in sql
    assert "GRANT SELECT, UPDATE ON sales.device_inventory, sales.license_inventory TO ffp_activation_app" in sql


def test_inventory_activation_sets_tenant_context_before_installation_lookup() -> None:
    text = POSTGRES_REPOSITORY.read_text(encoding="utf-8")
    activation = text[text.index("async def activate_inventory_atomically") :]

    assert activation.index("SELECT set_config('app.tenant_id'") < activation.index(
        "SELECT EXISTS (SELECT 1 FROM device.client_installations"
    )
