import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ANALYSIS = ROOT / "cloud/analysis/migrations/0001_analysis.sql"
ANALYSIS_PHYSICAL_CONTEXT = ROOT / "cloud/analysis/migrations/0002_physical_protocol_context.sql"
REPORTING = ROOT / "cloud/reporting/migrations/0001_reporting.sql"
OPS = ROOT / "cloud/observability/migrations/0001_ops.sql"


def normalized(path: Path) -> str:
    return re.sub(r"\s+", " ", path.read_text(encoding="utf-8")).lower()


class MigrationContractTests(unittest.TestCase):
    def test_task_d_migrations_exist_and_do_not_modify_ingestion_tables(self) -> None:
        for path in (ANALYSIS, ANALYSIS_PHYSICAL_CONTEXT, REPORTING, OPS):
            self.assertTrue(path.exists(), path)
            sql = normalized(path)
            self.assertNotIn("create table screening.", sql)
            self.assertNotIn("alter table screening.", sql)
            self.assertNotIn("create table device.", sql)

    def test_analysis_run_key_matches_versioned_recompute_contract(self) -> None:
        sql = normalized(ANALYSIS)

        self.assertIn("create schema if not exists analysis", sql)
        for field in (
            "tenant_id",
            "session_id",
            "pipeline_version",
            "algorithm_set_version",
            "model_set_version",
            "report_schema_version",
            "calibration_version",
            "payload_schema_version",
            "protocol_profile_version",
            "input_manifest_sha256",
            "parameters_sha256",
        ):
            self.assertIn(field, sql)
        self.assertRegex(
            sql,
            r"unique \(tenant_id, session_id, pipeline_version, algorithm_set_version, model_set_version, report_schema_version, calibration_version, payload_schema_version, protocol_profile_version, input_manifest_sha256, parameters_sha256\)",
        )
        self.assertIn("num_nonnulls(value_numeric, value_text, value_json) = 1", sql)
        self.assertIn("enable row level security", sql)

    def test_physical_context_identity_migration_is_fail_closed_and_versioned(self) -> None:
        sql = normalized(ANALYSIS_PHYSICAL_CONTEXT)
        self.assertIn("input_validation_status", sql)
        self.assertIn("validated", sql)
        self.assertIn("rejected", sql)
        self.assertIn("protocol_context_sha256", sql)
        self.assertIn("analysis_runs_recompute_identity_unique", sql)

    def test_reporting_enforces_one_report_per_session_and_immutable_versions(self) -> None:
        sql = normalized(REPORTING)

        self.assertIn("create schema if not exists reporting", sql)
        self.assertIn("unique (tenant_id, session_id)", sql)
        self.assertIn("unique (tenant_id, report_id, version_number)", sql)
        self.assertIn("cloud_complete", sql)
        self.assertIn("reject_immutable_report_row", sql)
        self.assertIn("report_artifacts", sql)
        self.assertIn("enable row level security", sql)

    def test_ops_migration_covers_outbox_telemetry_alerts_diagnostics_and_audit(self) -> None:
        sql = normalized(OPS)

        for table in (
            "outbox_events",
            "telemetry_batches",
            "alert_incidents",
            "diagnostic_packages",
            "support_audit_logs",
        ):
            self.assertIn(f"create table ops.{table}", sql)
        self.assertIn("unique (tenant_id, batch_id)", sql)
        self.assertIn("plaintext_sha256", sql)
        self.assertIn("ciphertext_sha256", sql)
        self.assertIn("runbook", sql)
        self.assertIn("enable row level security", sql)


if __name__ == "__main__":
    unittest.main()
