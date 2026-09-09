from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
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
    assert "& powershell " not in build.read_text(encoding="utf-8")
    assert "& $pwshExecutable " in build.read_text(encoding="utf-8")
    assert "Get-Command pwsh.exe -CommandType Application" in build.read_text(
        encoding="utf-8"
    )
    assert "$PSVersionTable.PSVersion.Major" in build.read_text(encoding="utf-8")
    assert "-lt 7" in build.read_text(encoding="utf-8")
    assert "-NoProfile" in build.read_text(encoding="utf-8")
    assert "require-signed" in verify.read_text(encoding="utf-8")
    assert "& powershell " not in verify.read_text(encoding="utf-8")
    assert "& $pwshExecutable " in verify.read_text(encoding="utf-8")
    assert "Get-Command pwsh.exe -CommandType Application" in verify.read_text(
        encoding="utf-8"
    )
    assert "$PSVersionTable.PSVersion.Major" in verify.read_text(encoding="utf-8")
    assert "-lt 7" in verify.read_text(encoding="utf-8")
    assert "-NoProfile" in verify.read_text(encoding="utf-8")


def test_portable_build_passes_named_arguments_to_the_release_verifier() -> None:
    build = (ROOT / "scripts" / "build-portable-release.ps1").read_text(
        encoding="utf-8"
    )

    assert "-ReleaseDirectory $releaseRoot" in build
    assert "@verificationArguments" not in build


def test_portable_release_uses_pwsh_for_build_and_verification_child_processes(
    tmp_path: Path,
) -> None:
    """Exercise the actual release scripts with a real PowerShell 7 child.

    The copied project's ``dev.ps1`` is the only test double: it controls the
    slow build-tool inputs while the release scripts resolve and launch the
    installed PowerShell 7 executable themselves.
    """

    pwsh = shutil.which("pwsh")
    if os.name != "nt" or pwsh is None:
        pytest.skip("requires Windows PowerShell 7")

    project = tmp_path / "project"
    scripts = project / "scripts"
    scripts.mkdir(parents=True)
    for name in (
        "build-portable-release.ps1",
        "verify-portable-release.ps1",
        "local-env.ps1",
    ):
        shutil.copy2(ROOT / "scripts" / name, scripts / name)
    (project / "pyproject.toml").write_text('version = "0.1.0"\n', encoding="utf-8")

    child_log = tmp_path / "child-pwsh.log"
    output_root = tmp_path / "output"
    (project / "dev.ps1").write_text(
        """param([Parameter(ValueFromRemainingArguments = $true)] [string[]] $InvocationArguments)
$InvocationArguments -join " " | Add-Content -LiteralPath $env:FEETFORCEPLATE_TEST_CHILD_LOG
if ($InvocationArguments -contains "PyInstaller") {
    $distIndex = [Array]::IndexOf($InvocationArguments, "--distpath")
    $applicationDirectory = Join-Path $InvocationArguments[$distIndex + 1] "FeetForcePlate"
    New-Item -ItemType Directory -Path $applicationDirectory -Force | Out-Null
    Set-Content -LiteralPath (Join-Path $applicationDirectory "FeetForcePlate.exe") -Value "application"
}
if ($InvocationArguments -contains "create") {
    $outputIndex = [Array]::IndexOf($InvocationArguments, "--output")
    $manifestPath = $InvocationArguments[$outputIndex + 1]
    Set-Content -LiteralPath $manifestPath -Value '{"signing_status":"unsigned-development"}'
}
exit 0
""",
        encoding="utf-8",
    )
    environment = {
        **os.environ,
        "FEETFORCEPLATE_TEST_CHILD_LOG": str(child_log),
        "FEETFORCEPLATE_TEST_OUTPUT_ROOT": str(output_root),
    }

    completed = subprocess.run(
        [
            pwsh,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(scripts / "build-portable-release.ps1"),
            "-OutputRoot",
            str(output_root),
            "-UnsignedDevelopment",
            "-GitCommit",
            "abc1234",
        ],
        cwd=project,
        capture_output=True,
        encoding="utf-8",
        env=environment,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    release = output_root / "release"
    assert (release / "FeetForcePlate-0.1.0-windows-x86_64.zip").is_file()
    assert (release / "FeetForcePlate-0.1.0-windows-x86_64.zip.sha256").is_file()
    assert (release / "release-manifest.json").is_file()
    child_calls = child_log.read_text(encoding="utf-8").splitlines()
    assert len(child_calls) == 3
    assert any("PyInstaller" in call for call in child_calls)
    assert any("portable_release create" in call for call in child_calls)
    assert any("portable_release verify" in call for call in child_calls)


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
