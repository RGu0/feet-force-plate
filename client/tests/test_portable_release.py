from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from zipfile import ZipFile

import pytest

from client.app.packaging.portable_release import (
    ReleaseVerificationError,
    create_manifest,
    verify_release_directory,
)


ROOT = Path(__file__).parents[2]


def _portable_archive(root: Path, *, include_specification: bool = True) -> Path:
    archive = root / "FeetForcePlate-0.1.0-windows-x86_64.zip"
    members = {
        "FeetForcePlate/FeetForcePlate.exe": b"application",
        "FeetForcePlate/_internal/client/app/assets/logo-horizontal-trimmed.png": b"logo",
    }
    if include_specification:
        members[
            "FeetForcePlate/_internal/docs/hardware/device-specifications/do-p4864/1.0.json"
        ] = b'{}'
    with ZipFile(archive, "w") as output:
        for name, payload in members.items():
            output.writestr(name, payload)
    return archive


def _write_manifest(root: Path, *, signing_status: str, include_specification: bool = True) -> None:
    archive = _portable_archive(root, include_specification=include_specification)
    manifest = create_manifest(
        archive=archive,
        app_version="0.1.0",
        git_commit="abc1234",
        signing_status=signing_status,
    )
    (root / "release-manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )


def test_verified_manifest_requires_signed_archive_and_runtime_resources(
    tmp_path: Path,
) -> None:
    _write_manifest(tmp_path, signing_status="signed")

    manifest = verify_release_directory(tmp_path, require_signed=True)

    assert manifest["signing_status"] == "signed"
    assert manifest["app_version"] == "0.1.0"


def test_unsigned_development_manifest_is_rejected_for_delivery(tmp_path: Path) -> None:
    _write_manifest(tmp_path, signing_status="unsigned-development")

    with pytest.raises(ReleaseVerificationError, match="unsigned-development"):
        verify_release_directory(tmp_path, require_signed=True)


def test_release_verification_rejects_an_archive_missing_device_specification(
    tmp_path: Path,
) -> None:
    _write_manifest(
        tmp_path,
        signing_status="unsigned-development",
        include_specification=False,
    )

    with pytest.raises(ReleaseVerificationError, match="device-specifications"):
        verify_release_directory(tmp_path, require_signed=False)


def test_portable_release_scripts_require_signing_and_delegate_to_contract() -> None:
    build = ROOT / "scripts" / "build-portable-release.ps1"
    verify = ROOT / "scripts" / "verify-portable-release.ps1"

    assert "FEETFORCEPLATE_SIGN_CERT_THUMBPRINT" in build.read_text(encoding="utf-8")
    assert "UnsignedDevelopment" in build.read_text(encoding="utf-8")
    assert "client.app.packaging.portable_release" in build.read_text(encoding="utf-8")
    assert "require-signed" in verify.read_text(encoding="utf-8")


def test_portable_build_passes_named_arguments_to_the_release_verifier() -> None:
    build = (ROOT / "scripts" / "build-portable-release.ps1").read_text(
        encoding="utf-8"
    )

    assert "-ReleaseDirectory $releaseRoot" in build
    assert "@verificationArguments" not in build


@pytest.mark.skipif(
    os.name != "nt" or shutil.which("pwsh") is None,
    reason="requires PowerShell 7 on Windows",
)
def test_portable_release_uses_pwsh_for_build_and_verification_child_processes() -> None:
    """A PS5 child cannot run the governed PS7 environment entrypoint."""

    outer_pwsh = shutil.which("pwsh")
    assert outer_pwsh is not None
    with tempfile.TemporaryDirectory() as temporary_directory:
        temporary_root = Path(temporary_directory)
        project_root = temporary_root / "project"
        scripts = project_root / "scripts"
        scripts.mkdir(parents=True)
        for name in (
            "build-portable-release.ps1",
            "verify-portable-release.ps1",
            "local-env.ps1",
        ):
            shutil.copy2(ROOT / "scripts" / name, scripts / name)
        (project_root / "pyproject.toml").write_text(
            '[project]\nversion = "0.1.0"\n', encoding="utf-8"
        )
        tool_directory = temporary_root / "tools"
        tool_directory.mkdir()
        child_log = temporary_root / "pwsh-child.log"
        (tool_directory / "pwsh.cmd").write_text(
            """@echo off
setlocal EnableExtensions EnableDelayedExpansion
echo %*>>\"%PACKAGER_PWSH_LOG%\"
set \"arguments=%*\"
set \"next=\"
set \"dist=\"
set \"output=\"
for %%A in (%*) do (
  if defined next (
    if \"!next!\"==\"dist\" set \"dist=%%~A\"
    if \"!next!\"==\"output\" set \"output=%%~A\"
    set \"next=\"
  ) else (
    if \"%%~A\"==\"--distpath\" set \"next=dist\"
    if \"%%~A\"==\"--output\" set \"next=output\"
  )
)
if not \"!arguments:PyInstaller=!\"==\"!arguments!\" (
  if not defined dist exit /b 41
  mkdir \"%dist%\\FeetForcePlate\" >nul 2>nul
  > \"%dist%\\FeetForcePlate\\FeetForcePlate.exe\" echo application
  exit /b 0
)
if defined output > \"%output%\" echo {\"signing_status\":\"unsigned-development\"}
exit /b 0
""",
            encoding="utf-8",
        )
        environment = os.environ.copy()
        environment["PACKAGER_PWSH_LOG"] = str(child_log)
        environment["PATH"] = str(tool_directory) + os.pathsep + environment["PATH"]
        environment["PATHEXT"] = ".CMD"
        output_root = temporary_root / "output"
        result = subprocess.run(
            [
                outer_pwsh,
                "-NoProfile",
                "-File",
                str(scripts / "build-portable-release.ps1"),
                "-OutputRoot",
                str(output_root),
                "-UnsignedDevelopment",
                "-GitCommit",
                "0" * 40,
            ],
            cwd=project_root,
            env=environment,
            capture_output=True,
            check=False,
        )

        stdout = result.stdout.decode("utf-8", errors="replace")
        stderr = result.stderr.decode("utf-8", errors="replace")
        assert result.returncode == 0, f"stdout:\n{stdout}\nstderr:\n{stderr}"
        release = output_root / "release"
        assert (release / "FeetForcePlate-0.1.0-windows-x86_64.zip").is_file()
        assert (release / "FeetForcePlate-0.1.0-windows-x86_64.zip.sha256").is_file()
        assert (release / "release-manifest.json").is_file()
        assert len(child_log.read_text(encoding="utf-8").splitlines()) >= 3


def test_portable_release_documentation_exposes_build_and_delivery_boundaries() -> None:
    guide = (
        ROOT / "docs" / "release" / "windows-portable-user-guide.md"
    ).read_text(encoding="utf-8")
    gate = (
        ROOT / "docs" / "release" / "windows-portable-release-gate.md"
    ).read_text(encoding="utf-8")

    assert "CH340" in guide
    assert "不得静默安装" in guide
    assert "Authenticode" in gate
    assert "真机" in gate
    assert "License" in gate
