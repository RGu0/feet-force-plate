from __future__ import annotations

import json
from pathlib import Path
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
