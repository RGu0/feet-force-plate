"""Prepare a public-only cloud-default bundle for controlled Windows use."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
import ssl

from .packaged_defaults import (
    CA_BUNDLE_NAME,
    CONFIG_NAME,
    LICENSE_PUBLIC_KEY_NAME,
    PackagedCloudDefaults,
    load_packaged_cloud_defaults,
)


APPROVAL_SCHEMA = "feetforceplate-windows-cloud-approval/1"
BUNDLE_SCHEMA = "feetforceplate-windows-cloud-bundle/1"
_APPROVAL_FIELDS = {
    "schema_version",
    "approval_state",
    "source",
    "approved_by",
    "approved_at",
    "environment",
    "target_commit",
}
_COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_LAUNCHER_TEMPLATE = _PROJECT_ROOT / "scripts" / "Invoke-FeetForcePlateCloudClient.ps1"
_README_TEMPLATE = _PROJECT_ROOT / "docs" / "release" / "windows-cloud-default-bundle.md"


@dataclass(frozen=True, slots=True)
class WindowsCloudBundle:
    delivery_directory: Path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_approval(path: Path, *, integration_mode: bool) -> dict[str, str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Windows cloud approval must be valid JSON") from exc
    if not isinstance(payload, dict) or set(payload) != _APPROVAL_FIELDS:
        raise ValueError("Windows cloud approval has an invalid schema")
    if any(not isinstance(value, str) for value in payload.values()):
        raise ValueError("Windows cloud approval has invalid values")
    if payload["schema_version"] != APPROVAL_SCHEMA:
        raise ValueError("Windows cloud approval has an invalid schema")
    if payload["approval_state"] != "approved":
        raise ValueError("Windows cloud approval is not approved")
    if not payload["source"].strip() or not payload["approved_by"].strip():
        raise ValueError("Windows cloud approval requires source and approver")
    try:
        datetime.fromisoformat(payload["approved_at"].replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Windows cloud approval has an invalid timestamp") from exc
    expected_environment = "integration" if integration_mode else "production"
    if payload["environment"] != expected_environment:
        raise ValueError("Windows cloud approval environment does not match config")
    if not _COMMIT_PATTERN.fullmatch(payload["target_commit"]):
        raise ValueError("Windows cloud approval requires a full target commit")
    return payload


def prepare_windows_cloud_default_bundle(
    *,
    source_directory: Path,
    approval_file: Path,
    delivery_directory: Path,
) -> WindowsCloudBundle:
    """Copy an approved public bundle and record hashes for sync validation."""

    source = source_directory.resolve()
    defaults = load_packaged_cloud_defaults(source)
    if defaults is None:
        raise ValueError("cloud default source must contain cloud-default.json")
    try:
        ssl.create_default_context(cafile=str(defaults.ca_bundle))
    except ssl.SSLError as exc:
        raise ValueError("cloud CA bundle is invalid") from exc
    approval = _load_approval(approval_file, integration_mode=defaults.integration_mode)
    destination = delivery_directory.resolve()
    if destination.exists():
        raise FileExistsError("Windows cloud delivery directory already exists")
    resources = destination / "public-cloud-defaults"
    resources.mkdir(parents=True)
    copied_paths = {
        "approval.json": destination / "approval.json",
        "Invoke-FeetForcePlateCloudClient.ps1": destination
        / "Invoke-FeetForcePlateCloudClient.ps1",
        "README.md": destination / "README.md",
        f"public-cloud-defaults/{CONFIG_NAME}": resources / CONFIG_NAME,
        f"public-cloud-defaults/{CA_BUNDLE_NAME}": resources / CA_BUNDLE_NAME,
        f"public-cloud-defaults/{LICENSE_PUBLIC_KEY_NAME}": resources
        / LICENSE_PUBLIC_KEY_NAME,
    }
    shutil.copyfile(approval_file, copied_paths["approval.json"])
    shutil.copyfile(_LAUNCHER_TEMPLATE, copied_paths["Invoke-FeetForcePlateCloudClient.ps1"])
    shutil.copyfile(_README_TEMPLATE, copied_paths["README.md"])
    for name in (CONFIG_NAME, CA_BUNDLE_NAME, LICENSE_PUBLIC_KEY_NAME):
        shutil.copyfile(source / name, resources / name)
    manifest = {
        "schema_version": BUNDLE_SCHEMA,
        "approval": approval,
        "config": {
            "api_base_url": defaults.base_url,
            "channel": "integration" if defaults.integration_mode else "distribution",
            "license_key_id": defaults.license_key_id,
        },
        "files": {path: _sha256(file) for path, file in copied_paths.items()},
    }
    (destination / "bundle-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return WindowsCloudBundle(delivery_directory=destination)


def validate_windows_cloud_default_bundle(
    delivery_directory: Path,
) -> PackagedCloudDefaults:
    """Fail closed unless a synced delivery still matches its approved manifest."""

    destination = delivery_directory.resolve()
    manifest_file = destination / "bundle-manifest.json"
    try:
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Windows cloud delivery manifest is invalid") from exc
    if not isinstance(manifest, dict) or set(manifest) != {
        "schema_version",
        "approval",
        "config",
        "files",
    }:
        raise ValueError("Windows cloud delivery manifest is invalid")
    if manifest["schema_version"] != BUNDLE_SCHEMA:
        raise ValueError("Windows cloud delivery manifest is invalid")
    files = manifest["files"]
    expected_files = {
        "approval.json",
        "Invoke-FeetForcePlateCloudClient.ps1",
        "README.md",
        f"public-cloud-defaults/{CONFIG_NAME}",
        f"public-cloud-defaults/{CA_BUNDLE_NAME}",
        f"public-cloud-defaults/{LICENSE_PUBLIC_KEY_NAME}",
    }
    if not isinstance(files, dict) or set(files) != expected_files:
        raise ValueError("Windows cloud delivery manifest is invalid")
    for relative_path, expected_digest in files.items():
        if not isinstance(expected_digest, str) or not re.fullmatch(
            r"[0-9a-f]{64}", expected_digest
        ):
            raise ValueError("Windows cloud delivery manifest is invalid")
        file = destination / relative_path
        if not file.is_file() or _sha256(file) != expected_digest:
            raise ValueError("Windows cloud delivery digest mismatch")
    resources = destination / "public-cloud-defaults"
    defaults = load_packaged_cloud_defaults(resources)
    if defaults is None:
        raise ValueError("Windows cloud delivery is missing public defaults")
    try:
        ssl.create_default_context(cafile=str(defaults.ca_bundle))
    except ssl.SSLError as exc:
        raise ValueError("cloud CA bundle is invalid") from exc
    approval = _load_approval(
        destination / "approval.json", integration_mode=defaults.integration_mode
    )
    expected_config = {
        "api_base_url": defaults.base_url,
        "channel": "integration" if defaults.integration_mode else "distribution",
        "license_key_id": defaults.license_key_id,
    }
    if manifest["approval"] != approval or manifest["config"] != expected_config:
        raise ValueError("Windows cloud delivery manifest is invalid")
    return defaults


__all__ = [
    "APPROVAL_SCHEMA",
    "BUNDLE_SCHEMA",
    "WindowsCloudBundle",
    "prepare_windows_cloud_default_bundle",
    "validate_windows_cloud_default_bundle",
]
