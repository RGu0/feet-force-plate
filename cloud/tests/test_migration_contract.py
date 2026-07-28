from __future__ import annotations

import re
import unittest
from pathlib import Path


MIGRATION = Path(__file__).parents[1] / "migrations" / "0001_p3_cloud_platform.sql"


class MigrationContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sql = MIGRATION.read_text(encoding="utf-8")

    def test_declares_owned_schemas_and_security_domains(self) -> None:
        for schema in ("iam", "device", "subject", "screening", "ops"):
            self.assertIn(f"CREATE SCHEMA IF NOT EXISTS {schema};", self.sql)

    def test_declares_ingestion_unique_keys_and_approved_status(self) -> None:
        self.assertRegex(
            self.sql,
            re.compile(r"UNIQUE\s*\(tenant_id,\s*session_id,\s*segment_index\)", re.I),
        )
        self.assertIn("'INGESTED'", self.sql)
        self.assertIn("manifest_sha256", self.sql)

    def test_tenant_tables_enable_and_force_rls(self) -> None:
        tenant_tables = (
            "iam.tenants",
            "iam.sites",
            "device.terminals",
            "device.devices",
            "device.terminal_device_bindings",
            "device.terminal_heartbeats",
            "subject.subjects",
            "subject.external_identifiers",
            "subject.analysis_profiles",
            "subject.consents",
            "screening.sessions",
            "screening.session_segments",
            "screening.session_manifests",
            "screening.ingest_problems",
            "ops.idempotency_keys",
            "ops.outbox_events",
            "ops.audit_logs",
        )
        for table in tenant_tables:
            self.assertIn(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;", self.sql)
            self.assertIn(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;", self.sql)
        self.assertIn("current_setting('app.tenant_id', true)::uuid", self.sql)

    def test_outbox_and_idempotency_are_first_class(self) -> None:
        self.assertIn("CREATE TABLE ops.idempotency_keys", self.sql)
        self.assertIn("request_sha256", self.sql)
        self.assertIn("CREATE TABLE ops.outbox_events", self.sql)
        self.assertIn("session.ingested.v1", self.sql)
        self.assertIn("WHERE published_at IS NULL", self.sql)

    def test_enrollment_code_can_prebind_an_approved_device(self) -> None:
        enrollment_table = self.sql.split(
            "CREATE TABLE device.enrollment_codes",
            maxsplit=1,
        )[1].split(");", maxsplit=1)[0]

        self.assertIn("device_id uuid", enrollment_table)
        self.assertIn(
            "FOREIGN KEY (tenant_id, device_id) REFERENCES device.devices(tenant_id, device_id)",
            enrollment_table,
        )

    def test_raw_identity_and_audit_records_are_separate_tables(self) -> None:
        self.assertIn("CREATE TABLE subject.identity_profiles", self.sql)
        self.assertIn("CREATE TABLE screening.session_segments", self.sql)
        self.assertIn("CREATE TABLE ops.audit_logs", self.sql)
        self.assertNotIn("external_id_plaintext", self.sql)


if __name__ == "__main__":
    unittest.main()
