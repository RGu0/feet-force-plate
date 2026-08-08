"""Portable Windows release manifest creation and verification."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
from typing import Any
from zipfile import BadZipFile, ZipFile


RELEASE_SCHEMA = "feetforceplate-portable-release/1"
TARGET = "windows-x86_64"
SIGNED = "signed"
UNSIGNED_DEVELOPMENT = "unsigned-development"
_ALLOWED_SIGNING_STATUSES = frozenset({SIGNED, UNSIGNED_DEVELOPMENT})
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
REQUIRED_ARCHIVE_MEMBERS = frozenset(
    {
        "FeetForcePlate/FeetForcePlate.exe",
        "FeetForcePlate/_internal/client/app/assets/logo-horizontal-trimmed.png",
        "FeetForcePlate/_internal/docs/hardware/device-specifications/do-p4864/1.0.json",
    }
)


class ReleaseVerificationError(ValueError):
    """Raised when a portable release cannot be safely delivered."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def create_manifest(
    *,
    archive: Path,
    app_version: str,
    git_commit: str,
    signing_status: str,
) -> dict[str, object]:
    archive = archive.resolve()
    if archive.suffix.lower() != ".zip" or not archive.is_file():
        raise ReleaseVerificationError("portable release archive must be an existing ZIP file")
    if signing_status not in _ALLOWED_SIGNING_STATUSES:
        raise ReleaseVerificationError("portable release signing status is invalid")
    if not app_version.strip() or not git_commit.strip():
        raise ReleaseVerificationError("app_version and git_commit are required")
    return {
        "schema_version": RELEASE_SCHEMA,
        "app_version": app_version,
        "git_commit": git_commit,
        "target": TARGET,
        "created_at": datetime.now(UTC).isoformat(),
        "signing_status": signing_status,
        "archive": {"filename": archive.name, "sha256": sha256_file(archive)},
        "application_executable": "FeetForcePlate/FeetForcePlate.exe",
    }


def verify_release_directory(
    release_dir: Path, *, require_signed: bool
) -> dict[str, object]:
    release_dir = release_dir.resolve()
    manifest_path = release_dir / "release-manifest.json"
    try:
        raw_manifest: Any = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReleaseVerificationError("release-manifest.json is invalid") from exc
    if not isinstance(raw_manifest, dict):
        raise ReleaseVerificationError("release manifest must be a JSON object")
    manifest = raw_manifest
    _validate_manifest_shape(manifest)
    signing_status = manifest["signing_status"]
    if require_signed and signing_status != SIGNED:
        raise ReleaseVerificationError("unsigned-development release cannot be delivered")

    archive_data = manifest["archive"]
    assert isinstance(archive_data, dict)
    archive_name = archive_data["filename"]
    assert isinstance(archive_name, str)
    archive = release_dir / archive_name
    if not archive.is_file():
        raise ReleaseVerificationError("portable release archive is missing")
    expected_digest = archive_data["sha256"]
    assert isinstance(expected_digest, str)
    if sha256_file(archive) != expected_digest:
        raise ReleaseVerificationError("portable release archive SHA-256 does not match")
    _validate_archive_members(archive)
    return manifest


def _validate_manifest_shape(manifest: dict[str, object]) -> None:
    required = {
        "schema_version",
        "app_version",
        "git_commit",
        "target",
        "created_at",
        "signing_status",
        "archive",
        "application_executable",
    }
    if set(manifest) != required:
        raise ReleaseVerificationError("release manifest has an invalid schema")
    if manifest["schema_version"] != RELEASE_SCHEMA or manifest["target"] != TARGET:
        raise ReleaseVerificationError("release manifest has an unsupported schema or target")
    for field in ("app_version", "git_commit", "created_at", "application_executable"):
        if not isinstance(manifest[field], str) or not manifest[field].strip():
            raise ReleaseVerificationError(f"release manifest {field} is invalid")
    if manifest["application_executable"] not in REQUIRED_ARCHIVE_MEMBERS:
        raise ReleaseVerificationError("release manifest application executable is invalid")
    if manifest["signing_status"] not in _ALLOWED_SIGNING_STATUSES:
        raise ReleaseVerificationError("release manifest signing status is invalid")
    archive = manifest["archive"]
    if not isinstance(archive, dict) or set(archive) != {"filename", "sha256"}:
        raise ReleaseVerificationError("release manifest archive is invalid")
    filename = archive["filename"]
    digest = archive["sha256"]
    if (
        not isinstance(filename, str)
        or Path(filename).name != filename
        or not filename.endswith(".zip")
        or not isinstance(digest, str)
        or not _SHA256_RE.fullmatch(digest)
    ):
        raise ReleaseVerificationError("release manifest archive is invalid")


def _validate_archive_members(archive: Path) -> None:
    try:
        with ZipFile(archive) as bundle:
            names = frozenset(bundle.namelist())
    except (BadZipFile, OSError) as exc:
        raise ReleaseVerificationError("portable release archive is invalid") from exc
    missing = REQUIRED_ARCHIVE_MEMBERS - names
    if missing:
        raise ReleaseVerificationError(
            "portable release archive is missing required resources: "
            + ", ".join(sorted(missing))
        )


def _write_manifest(path: Path, manifest: dict[str, object]) -> None:
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _main() -> int:
    parser = argparse.ArgumentParser(description="Create or verify a portable release")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create")
    create.add_argument("--archive", type=Path, required=True)
    create.add_argument("--app-version", required=True)
    create.add_argument("--git-commit", required=True)
    create.add_argument("--signing-status", choices=sorted(_ALLOWED_SIGNING_STATUSES), required=True)
    create.add_argument("--output", type=Path, required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("--release-directory", type=Path, required=True)
    verify.add_argument("--require-signed", action="store_true")
    arguments = parser.parse_args()
    try:
        if arguments.command == "create":
            manifest = create_manifest(
                archive=arguments.archive,
                app_version=arguments.app_version,
                git_commit=arguments.git_commit,
                signing_status=arguments.signing_status,
            )
            _write_manifest(arguments.output, manifest)
        else:
            manifest = verify_release_directory(
                arguments.release_directory, require_signed=arguments.require_signed
            )
    except ReleaseVerificationError as exc:
        parser.error(str(exc))
    print(json.dumps(manifest, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
