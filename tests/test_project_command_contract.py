"""Regression contracts for governed FeetForcePlate project commands."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ProjectCommandContractTests(unittest.TestCase):
    @unittest.skipUnless(
        os.name == "nt" and shutil.which("pwsh"),
        "requires PowerShell 7 on Windows",
    )
    def test_windows_setup_accepts_no_extra_arguments_under_strict_mode(self) -> None:
        """Ensure setup uses uv's managed interpreter without a global Python command."""

        with tempfile.TemporaryDirectory() as temporary_directory:
            uv_stub = Path(temporary_directory) / "uv-stub.cmd"
            python_stub = Path(temporary_directory) / "managed-python.cmd"
            uv_stub.write_text(
                '@if "%~1"=="python" if "%~2"=="install" '
                'if "%~3"=="--managed-python" if "%~4"=="3.11.9" if "%~5"=="" @exit /b 0\r\n'
                '@if "%~1"=="python" if "%~2"=="find" '
                'if "%~3"=="--managed-python" if "%~4"=="" (\r\n'
                f'@echo {python_stub}\r\n'
                "@exit /b 0\r\n"
                ")\r\n"
                "@if \"%~1\"==\"python\" @exit /b 1\r\n"
                "@exit /b 0\r\n",
                encoding="utf-8",
            )
            python_stub.write_text(
                '@if "%~1"=="scripts/prepare_foundation_artifact.py" '
                'if "%~2"=="--download" if "%~3"=="" @exit /b 0\r\n'
                "@exit /b 1\r\n",
                encoding="utf-8",
            )
            environment = os.environ.copy()
            environment["UV_BIN"] = str(uv_stub)
            environment["PATH"] = temporary_directory
            result = subprocess.run(
                ["pwsh", "-NoProfile", "-File", str(PROJECT_ROOT / "dev.ps1"), "setup"],
                cwd=PROJECT_ROOT,
                env=environment,
                capture_output=True,
                check=False,
            )

        stdout = result.stdout.decode("utf-8", errors="replace")
        stderr = result.stderr.decode("utf-8", errors="replace")
        self.assertEqual(
            result.returncode,
            0,
            f"dev.ps1 setup failed:\nstdout:\n{stdout}\nstderr:\n{stderr}",
        )

    def test_platform_entrypoints_and_manifest_use_locked_governed_commands(self) -> None:
        unix_entrypoint = PROJECT_ROOT / "dev"
        windows_entrypoint = PROJECT_ROOT / "dev.ps1"
        manifest = PROJECT_ROOT / ".ai-project" / "project.yaml"

        self.assertTrue(unix_entrypoint.is_file())
        self.assertTrue(windows_entrypoint.is_file())
        self.assertTrue(manifest.is_file())
        if os.name != "nt":
            self.assertTrue(unix_entrypoint.stat().st_mode & 0o111)

        unix = unix_entrypoint.read_text(encoding="utf-8")
        windows = windows_entrypoint.read_text(encoding="utf-8")
        config = manifest.read_text(encoding="utf-8")
        for action in ("setup", "test", "lint", "build"):
            self.assertIn(f'    {action}: ["./dev", "{action}"]', config)
            self.assertIn(f'    {action}: ["pwsh", "-File", "dev.ps1", "{action}"]', config)
        self.assertIn("sync --locked --extra dev", unix)
        self.assertIn("run --locked --extra dev", unix)
        self.assertIn("centralized-project-envs", unix)
        self.assertNotIn("export UV_PROJECT_ENVIRONMENT", unix)
        self.assertNotIn("$env:UV_PROJECT_ENVIRONMENT =", windows)
        self.assertIn("prepare_foundation_artifact.py --download", unix)
        self.assertIn("--find-links .foundation-artifacts", unix)
        self.assertNotIn("build packages/techflex-cloud-foundation", unix)
        self.assertNotIn("record_foundation_release_baseline.py", unix)
        self.assertIn("scripts/prepare_foundation_artifact.py", windows)
        self.assertIn('"--download"', windows)
        self.assertIn("--find-links", windows)
        self.assertNotIn("build packages/techflex-cloud-foundation", windows)
        self.assertNotIn("record_foundation_release_baseline.py", windows)

    def test_redundant_foundation_source_is_not_retained_in_the_consumer(self) -> None:
        self.assertFalse((PROJECT_ROOT / "packages/techflex-cloud-foundation").exists())
        self.assertFalse((PROJECT_ROOT / "scripts/record_foundation_release_baseline.py").exists())
        self.assertTrue((PROJECT_ROOT / "scripts/prepare_foundation_artifact.py").is_file())

    def test_private_release_download_requires_a_dedicated_read_only_secret(self) -> None:
        workflow = (PROJECT_ROOT / ".github" / "workflows" / "quality.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn("TECHFLEX_FOUNDATION_RELEASE_TOKEN", workflow)
        self.assertNotIn("GH_TOKEN: ${{ github.token }}", workflow)


if __name__ == "__main__":
    unittest.main()
