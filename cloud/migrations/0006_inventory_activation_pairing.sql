BEGIN;

-- A License must be delivered with one specific labelled device.  The initial
-- inventory migration stored both lists per batch but did not preserve that
-- pairing, which would otherwise permit a code from the same batch to bind a
-- different device label.
ALTER TABLE sales.license_inventory
    ADD COLUMN device_inventory_id uuid REFERENCES sales.device_inventory(device_inventory_id);

DO $existing_inventory$
BEGIN
    IF EXISTS (SELECT 1 FROM sales.license_inventory) THEN
        RAISE EXCEPTION
            'existing sales inventory requires an audited device-to-code import before migration 0006';
    END IF;
END
$existing_inventory$;

ALTER TABLE sales.license_inventory
    ALTER COLUMN device_inventory_id SET NOT NULL;
ALTER TABLE sales.license_inventory
    ADD CONSTRAINT license_inventory_device_inventory_id_key UNIQUE (device_inventory_id);

GRANT USAGE ON SCHEMA sales TO ffp_activation_app;
GRANT SELECT, UPDATE ON sales.device_inventory, sales.license_inventory TO ffp_activation_app;
GRANT INSERT ON sales.inventory_activations TO ffp_activation_app;
GRANT INSERT ON iam.tenants TO ffp_activation_app;
GRANT INSERT ON device.hardware_assets, device.license_assignments,
    device.hardware_bindings TO ffp_activation_app;
GRANT INSERT ON device.hardware_identity_directory TO ffp_activation_app;

COMMIT;
