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
    @unittest.skipUnless(shutil.which("pwsh"), "requires PowerShell 7")
    def test_windows_setup_accepts_no_extra_arguments_under_strict_mode(self) -> None:
        """Catch the unbound Command parameter regression in the real entrypoint."""

        with tempfile.TemporaryDirectory() as temporary_directory:
            uv_stub = Path(temporary_directory) / "uv-stub.cmd"
            uv_stub.write_text("@exit /b 0\r\n", encoding="utf-8")
            environment = os.environ.copy()
            environment["UV_BIN"] = str(uv_stub)
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
        self.assertIn("build packages/techflex-cloud-foundation", unix)
        self.assertIn("record_foundation_release_baseline.py", unix)
        self.assertIn("--baseline-strategy legacy-httpx-client/1", unix)
        self.assertIn("build packages/techflex-cloud-foundation", windows)
        self.assertIn("record_foundation_release_baseline.py", windows)
        self.assertIn("--baseline-strategy legacy-httpx-client/1", windows)


if __name__ == "__main__":
    unittest.main()
