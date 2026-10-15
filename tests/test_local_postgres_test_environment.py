from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts import local_postgres_test_environment as postgres_test


class RuntimePathValidationTests(unittest.TestCase):
    @staticmethod
    def _create_reparse_directory(link: Path, target: Path) -> None:
        target.mkdir(parents=True)
        if os.name == "nt":
            powershell = shutil.which("pwsh") or shutil.which("powershell.exe")
            if powershell is None:
                raise unittest.SkipTest("PowerShell is unavailable for Windows junction creation")
            environment = os.environ.copy()
            environment["RAY513_JUNCTION_PATH"] = str(link)
            environment["RAY513_JUNCTION_TARGET"] = str(target)
            result = subprocess.run(
                [
                    powershell,
                    "-NoLogo",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    "New-Item -ItemType Junction -Path $env:RAY513_JUNCTION_PATH "
                    "-Target $env:RAY513_JUNCTION_TARGET | Out-Null",
                ],
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                detail = (result.stdout + result.stderr).strip()
                raise unittest.SkipTest(
                    "Windows directory junction creation is unavailable: "
                    + detail[:200]
                )
        else:
            link.symlink_to(target, target_is_directory=True)

    def test_fixed_runtime_path_without_reparse_components_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ray513-runtime-safe-") as directory:
            runtime_root = Path(directory) / "runtime"
            with patch.object(postgres_test, "RUNTIME_ROOT", runtime_root):
                postgres_test.validate_target(
                    postgres_test.HOST,
                    postgres_test.PORT,
                    postgres_test.DATABASE,
                    runtime_root,
                )
            self.assertFalse(runtime_root.exists())

    def test_ancestor_junction_is_rejected_before_private_runtime_writes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ray513-runtime-ancestor-junction-") as directory:
            fixture_root = Path(directory)
            redirected_root = fixture_root / "redirected-local-target"
            junction = fixture_root / "ancestor-junction"
            self._create_reparse_directory(junction, redirected_root)
            runtime_root = junction / "local-labs" / "ray513-test"

            with (
                patch.object(postgres_test, "RUNTIME_ROOT", runtime_root),
                patch.object(postgres_test, "DATA_ROOT", runtime_root / "data"),
                patch.object(postgres_test, "PRIVATE_ROOT", runtime_root / "private"),
                patch.object(postgres_test, "LOG_ROOT", runtime_root / "logs"),
                patch.object(postgres_test.os, "name", "nt"),
                patch.object(postgres_test, "_verify_acl") as verify_acl,
                patch.object(postgres_test, "_verify_acls") as verify_acls,
            ):
                with self.assertRaisesRegex(ValueError, "reparse point"):
                    postgres_test._ensure_private_root()

            verify_acl.assert_not_called()
            verify_acls.assert_not_called()
            self.assertFalse((redirected_root / "local-labs").exists())

    def test_runtime_leaf_reparse_point_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ray513-runtime-leaf-junction-") as directory:
            fixture_root = Path(directory)
            target = fixture_root / "target"
            target.mkdir()
            runtime_root = fixture_root / "runtime-junction"
            if os.name == "nt":
                # The shared helper owns the temporary target as well as the
                # junction creation details; both remain inside this fixture.
                runtime_root.unlink(missing_ok=True)
                target.rmdir()
                self._create_reparse_directory(runtime_root, target)
            else:
                runtime_root.symlink_to(target, target_is_directory=True)

            with patch.object(postgres_test, "RUNTIME_ROOT", runtime_root):
                with self.assertRaisesRegex(ValueError, "reparse point"):
                    postgres_test.validate_target(
                        postgres_test.HOST,
                        postgres_test.PORT,
                        postgres_test.DATABASE,
                        runtime_root,
                    )


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
