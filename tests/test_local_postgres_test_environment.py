from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

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
            runtime_root = Path(directory).resolve() / "runtime"
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
            fixture_root = Path(directory).resolve()
            redirected_root = fixture_root / "redirected-local-target"
            junction = fixture_root / "ancestor-junction"
            self._create_reparse_directory(junction, redirected_root)
            runtime_root = junction / "local-labs" / "ray513-test"

            with (
                patch.object(postgres_test, "RUNTIME_ROOT", runtime_root),
                patch.object(postgres_test, "DATA_ROOT", runtime_root / "data"),
                patch.object(postgres_test, "PRIVATE_ROOT", runtime_root / "private"),
                patch.object(postgres_test, "LOG_ROOT", runtime_root / "logs"),
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
            fixture_root = Path(directory).resolve()
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
        from techflex_cloud_foundation.schema import MigrationStep

        recorded_sql, pending_sql = "SELECT 'recorded';", "SELECT 'retry';"
        plan = tuple(
            MigrationStep(step_id=name, filename=None, inline_sql=sql, converges=True,
                          sha256=hashlib.sha256(sql.encode()).hexdigest())
            for name, sql in (("recorded", recorded_sql), ("pending", pending_sql))
        )

        class Connection:
            def __init__(self):
                self.ledger = {"recorded": plan[0].sha256}
                self.executed = []
                self.fail_once = True
                self.closed = 0

            def is_in_transaction(self):
                return False

            async def fetchval(self, _query, *_args):
                return True  # The packaged runner ledger already exists.

            async def fetch(self, _query):
                return [{"migration_id": key, "sha256": value}
                        for key, value in self.ledger.items()]

            async def execute(self, query, *args):
                if query in (recorded_sql, pending_sql):
                    self.executed.append(query)
                    if self.fail_once:
                        self.fail_once = False
                        raise RuntimeError("interrupted SQL")
                if query.startswith("INSERT INTO ops.schema_migrations"):
                    self.ledger[args[0]] = args[1]
                return "OK"

            async def close(self):
                self.closed += 1

        connection = Connection()
        with (
            patch.object(postgres_test, "DEFAULT_PLAN", plan),
            patch.object(postgres_test.asyncpg, "connect", new=AsyncMock(return_value=connection)) as connect,
            patch.object(postgres_test, "_psql") as psql,
        ):
            with self.assertRaisesRegex(RuntimeError, "migration failed"):
                postgres_test._apply_migrations({"admin": "admin-secret"})
            psql.assert_not_called()
            postgres_test._apply_migrations({"admin": "admin-secret"})
            postgres_test._apply_migrations({"admin": "admin-secret"})
        self.assertEqual(connection.executed, [pending_sql, pending_sql])
        self.assertEqual(connection.ledger["pending"], plan[1].sha256)
        self.assertEqual(connection.closed, 3)
        self.assertTrue(all(call.kwargs["timeout"] == 5 for call in connect.call_args_list))
        self.assertTrue(all("127.0.0.1:55432/ffp_ray513_test" in call.args[0]
                            for call in connect.call_args_list))
        self.assertEqual(psql.call_count, 2)
        self.assertIn("WITH INHERIT TRUE", psql.call_args.kwargs["sql"])

    def test_packaged_migration_connection_error_does_not_expose_credentials(self) -> None:
        with (
            patch.object(postgres_test.asyncpg, "connect", new=AsyncMock(
                side_effect=OSError("postgresql://admin:admin-secret@127.0.0.1:55432/private"))),
            patch.object(postgres_test, "_psql") as psql,
        ):
            with self.assertRaisesRegex(RuntimeError, "migration failed") as raised:
                postgres_test._apply_migrations({"admin": "admin-secret"})
        self.assertNotIn("admin-secret", str(raised.exception))
        psql.assert_not_called()

    def test_packaged_schema_failure_closes_connection_and_does_not_grant(self) -> None:
        connection = SimpleNamespace(close=AsyncMock())
        with (
            patch.object(postgres_test.asyncpg, "connect", new=AsyncMock(return_value=connection)),
            patch.object(postgres_test, "apply_migrations", new=AsyncMock(
                side_effect=RuntimeError("checksum mismatch"))) as migrate,
            patch.object(postgres_test, "_psql") as psql,
        ):
            with self.assertRaisesRegex(RuntimeError, "migration failed"):
                postgres_test._apply_migrations({"admin": "admin-secret"})
        migrate.assert_awaited_once_with(connection, plan=postgres_test.DEFAULT_PLAN)
        connection.close.assert_awaited_once()
        psql.assert_not_called()

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
        with (
            patch.object(postgres_test.shutil, "which", return_value="pwsh"),
            patch.object(postgres_test, "_run") as run,
        ):
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


class LiveSuiteDispatchTests(unittest.TestCase):
    def test_live_action_preserves_released_capture_recovery_and_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "released"
            source.mkdir()
            results = [SimpleNamespace(returncode=2, stdout="consumer failure", stderr=""),
                       SimpleNamespace(returncode=0, stdout="capture/recovery passed", stderr="")]
            dsns = {"FEETFORCEPLATE_TEST_ADMIN_DSN": "private-dsn"}
            with patch.object(postgres_test, "_load_credentials", return_value={"admin": "private-secret"}), \
                 patch.object(postgres_test, "_validate_role_contract", return_value={}), \
                 patch.object(postgres_test, "_role_dsns", return_value=dsns), \
                 patch.object(postgres_test, "foundation_source_root", return_value=source), \
                 patch.object(postgres_test, "LOG_ROOT", Path(temporary)), \
                 patch.object(postgres_test.subprocess, "run", side_effect=results) as run:
                self.assertEqual(postgres_test._live_tests(), 2)
            self.assertEqual(run.call_count, 2)
            consumer, released = run.call_args_list
            self.assertEqual(consumer.kwargs["cwd"], postgres_test.REPOSITORY_ROOT)
            self.assertTrue(set(postgres_test.TEST_FILES).issubset(consumer.args[0]))
            self.assertEqual(released.kwargs["cwd"], source)
            for name in ("tests/test_ffp_postgres_capture_grants.py", "tests/test_ffp_identity_recovery_postgres_live.py"):
                self.assertIn(name, released.args[0])
            self.assertIn("no:cacheprovider", released.args[0])
            self.assertEqual(released.kwargs["env"]["PYTHONDONTWRITEBYTECODE"], "1")
            self.assertEqual(released.kwargs["env"]["FEETFORCEPLATE_TEST_ADMIN_DSN"], "private-dsn")
            self.assertTrue(released.kwargs["env"]["PYTHONPATH"].startswith(str(source) + os.pathsep))
