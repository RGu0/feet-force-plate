from __future__ import annotations

import subprocess
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts import local_postgres_test_environment as postgres_test


class RunFailureTests(unittest.TestCase):
    def test_migration_resume_skips_recorded_files_and_retries_unrecorded_files(self) -> None:
        migrations = [Path("0001.sql"), Path("0010.sql")]
        with (
            patch.object(postgres_test, "_psql", side_effect=["", "t", "f", "", "", ""] ) as psql,
            patch.object(Path, "glob", return_value=migrations),
        ):
            postgres_test._apply_migrations({"admin": "admin-secret"})
        calls = psql.call_args_list
        self.assertIn("CREATE TABLE IF NOT EXISTS", calls[0].kwargs["sql"])
        self.assertEqual(calls[1].kwargs["query"], "SELECT EXISTS (SELECT 1 FROM public.ffp_ray513_test_migrations WHERE name = '0001.sql')")
        self.assertEqual(calls[2].kwargs["query"], "SELECT EXISTS (SELECT 1 FROM public.ffp_ray513_test_migrations WHERE name = '0010.sql')")
        self.assertEqual(calls[3].kwargs["file"], migrations[1])

    def test_server_identity_check_normalizes_loopback_address(self) -> None:
        credentials = {"admin": "admin-secret", "tenant": "tenant-secret",
                      "activation": "activation-secret", "platform": "platform-secret"}
        with (
            patch.object(postgres_test, "_load_credentials", return_value=credentials),
            patch.object(postgres_test, "_is_running", return_value=True),
            patch.object(postgres_test, "_psql_as", return_value="127.0.0.1|55432|postgres") as psql,
        ):
            postgres_test._validate_server(database="postgres")
        self.assertIn("host(inet_server_addr())", psql.call_args.args[2])

    def test_postgres_start_does_not_capture_inherited_server_pipes(self) -> None:
        with (
            patch.object(postgres_test, "_binary", return_value=Path("pg_ctl.exe")),
            patch.object(postgres_test, "_run") as run,
        ):
            postgres_test._pg_ctl("--log", "postgres.log", "--wait", "start")
        self.assertFalse(run.call_args.kwargs["capture_output"])

    def test_acl_verification_batches_paths_into_one_process(self) -> None:
        paths = [Path(r"C:\private\data"), Path(r"C:\private\credentials.json")]
        with patch.object(postgres_test, "_run") as run:
            postgres_test._verify_acls(paths)
        arguments = run.call_args.args[0]
        self.assertEqual(arguments[-3:], ["-Action", "verify", "-Path", ";".join(map(str, paths))][-3:])
        run.assert_called_once()

    def test_existing_runtime_acl_is_checked_once_per_action(self) -> None:
        with (
            patch.object(postgres_test.os, "name", "nt"),
            patch.object(postgres_test, "_require_private_root") as require_private_root,
            patch.object(postgres_test, "_status"),
        ):
            self.assertEqual(postgres_test.main(["status"]), 0)
        require_private_root.assert_called_once_with()

    def test_local_connections_have_a_bounded_connect_timeout(self) -> None:
        environment = postgres_test._safe_pg_environment("private-secret")
        self.assertEqual(environment["PGCONNECT_TIMEOUT"], "5")
        self.assertEqual(environment["PGPASSWORD"], "private-secret")

    def test_command_failure_reports_sanitized_stderr(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["psql"], returncode=2, stdout="", stderr="psql: database does not exist\n"
        )
        with patch.object(postgres_test.subprocess, "run", return_value=completed):
            with self.assertRaisesRegex(
                RuntimeError,
                "isolated PostgreSQL SQL operation failed with exit code 2: psql: database does not exist",
            ):
                postgres_test._run(
                    ["psql"],
                    operation="isolated PostgreSQL SQL operation",
                    environment={"PGPASSWORD": "private-secret"},
                )

    def test_command_failure_redacts_password_from_stderr(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["psql"], returncode=2, stdout="", stderr="psql: rejected private-secret\n"
        )
        with patch.object(postgres_test.subprocess, "run", return_value=completed):
            with self.assertRaises(RuntimeError) as raised:
                postgres_test._run(
                    ["psql"],
                    operation="isolated PostgreSQL SQL operation",
                    environment={"PGPASSWORD": "private-secret"},
                )
        self.assertNotIn("private-secret", str(raised.exception))
        self.assertIn("<redacted>", str(raised.exception))
