"""Regression contracts for the locked foundation artifact bootstrap (RAY-389)."""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_module():
    specification = importlib.util.spec_from_file_location(
        "prepare_foundation_artifact",
        PROJECT_ROOT / "scripts" / "prepare_foundation_artifact.py",
    )
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


class PrepareFoundationArtifactTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_module()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.cache = self.root / ".foundation-artifacts"
        self.wheel_bytes = b"foundation-wheel-bytes"
        self.wheel_name = "techflex_cloud_foundation-0.1.1-py3-none-any.whl"
        lock_path = self.root / "foundation-artifact.lock.json"
        lock_path.write_text(
            json.dumps(
                {
                    "package": "techflex-cloud-foundation",
                    "release": "v0.1.1",
                    "version": "0.1.1",
                    "wheel": self.wheel_name,
                    "sha256": hashlib.sha256(self.wheel_bytes).hexdigest(),
                }
            ),
            encoding="utf-8",
        )
        self.module.LOCK_PATH = lock_path
        self.module.CACHE_DIRECTORY = self.cache

    def _write_gh_stub(self, script_body: str) -> str:
        stub = self.root / "gh-stub"
        stub.write_text("#!/usr/bin/env bash\n" + script_body, encoding="utf-8")
        stub.chmod(stub.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        return str(stub)

    def _write_cached_wheel(self, content: bytes) -> Path:
        self.cache.mkdir(parents=True, exist_ok=True)
        artifact = self.cache / self.wheel_name
        artifact.write_bytes(content)
        return artifact

    def test_existing_verified_wheel_needs_no_download(self) -> None:
        artifact = self._write_cached_wheel(self.wheel_bytes)
        self.assertEqual(self.module.ensure_artifact(download=False), artifact)

    def test_missing_wheel_without_download_points_to_setup_not_the_lockfile(self) -> None:
        with self.assertRaises(RuntimeError) as context:
            self.module.ensure_artifact(download=False)
        message = str(context.exception)
        self.assertIn("./dev setup", message)
        self.assertNotIn("uv.lock", message)

    def test_mismatched_cached_wheel_without_download_is_refused(self) -> None:
        self._write_cached_wheel(b"tampered-bytes")
        with self.assertRaises(RuntimeError) as context:
            self.module.ensure_artifact(download=False)
        self.assertIn("./dev setup", str(context.exception))

    def test_download_writes_a_verified_wheel(self) -> None:
        gh = self._write_gh_stub(
            'directory=""\n'
            'previous=""\n'
            'for argument in "$@"; do\n'
            '  if [ "$previous" = "--dir" ]; then directory="$argument"; fi\n'
            '  previous="$argument"\n'
            "done\n"
            f'printf \'%s\' "foundation-wheel-bytes" > "$directory/{self.wheel_name}"\n'
        )
        with mock.patch("shutil.which", return_value=gh):
            artifact = self.module.ensure_artifact(download=True)
        self.assertEqual(artifact.read_bytes(), self.wheel_bytes)

    def test_download_failure_points_to_authentication_and_setup(self) -> None:
        gh = self._write_gh_stub("exit 4\n")
        with mock.patch("shutil.which", return_value=gh):
            with self.assertRaises(RuntimeError) as context:
                self.module.ensure_artifact(download=True)
        message = str(context.exception)
        self.assertIn("gh auth login", message)
        self.assertIn("./dev setup", message)
        self.assertNotIn("uv.lock", message)
        self.assertIsInstance(context.exception.__cause__, subprocess.CalledProcessError)

    def test_downloaded_wheel_failing_verification_is_refused(self) -> None:
        gh = self._write_gh_stub(
            'directory=""\n'
            'previous=""\n'
            'for argument in "$@"; do\n'
            '  if [ "$previous" = "--dir" ]; then directory="$argument"; fi\n'
            '  previous="$argument"\n'
            "done\n"
            f'printf \'%s\' "tampered-bytes" > "$directory/{self.wheel_name}"\n'
        )
        with mock.patch("shutil.which", return_value=gh):
            with self.assertRaises(RuntimeError) as context:
                self.module.ensure_artifact(download=True)
        self.assertIn("SHA-256", str(context.exception))

    def test_missing_github_cli_is_reported(self) -> None:
        with mock.patch("shutil.which", return_value=None):
            with self.assertRaises(RuntimeError) as context:
                self.module.ensure_artifact(download=True)
        self.assertIn("GitHub CLI is required", str(context.exception))

    def test_main_reports_bootstrap_failure_without_a_traceback(self) -> None:
        stderr = io.StringIO()
        with mock.patch.object(sys, "argv", ["prepare_foundation_artifact.py"]):
            with contextlib.redirect_stderr(stderr):
                exit_code = self.module.main()
        self.assertEqual(exit_code, 1)
        self.assertIn("foundation artifact preparation failed", stderr.getvalue())
        self.assertIn("./dev setup", stderr.getvalue())


class BootstrapOrderingContractTests(unittest.TestCase):
    def test_unix_setup_downloads_the_artifact_before_locked_sync(self) -> None:
        entrypoint = (PROJECT_ROOT / "dev").read_text(encoding="utf-8")
        setup_block = entrypoint.split("setup)", 1)[1].split(";;", 1)[0]
        download = setup_block.index("prepare_foundation_artifact.py --download")
        self.assertLess(download, setup_block.index("sync\n"))


if __name__ == "__main__":
    unittest.main()
