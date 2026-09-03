"""Prepare and validate a signed public cloud-default bundle for Windows."""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import ssl
import stat
import subprocess
import tempfile

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .packaged_defaults import (
    CA_BUNDLE_NAME,
    CONFIG_NAME,
    LICENSE_PUBLIC_KEY_NAME,
    PackagedCloudDefaults,
    load_packaged_cloud_defaults,
)


APPROVAL_SCHEMA = "feetforceplate-windows-cloud-approval/2"
_APPROVAL_FIELDS = {
    "schema_version", "approval_state", "source", "approved_by", "approved_at",
    "environment", "target_commit", "config", "files",
}
_CONFIG_FIELDS = {"api_base_url", "channel", "license_key_id"}
_RESOURCE_FILES = {
    f"public-cloud-defaults/{CONFIG_NAME}",
    f"public-cloud-defaults/{CA_BUNDLE_NAME}",
    f"public-cloud-defaults/{LICENSE_PUBLIC_KEY_NAME}",
}
_DELIVERY_FILES = {"approval.json", "approval.sig"}
_COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")

# Dedicated RAY-321 approval verifier. Never load this trust anchor from sync
# storage or substitute the License verification key.
_TRUSTED_APPROVAL_PUBLIC_KEY = base64.b64decode(
    "dp6+fAoMoq0hwyaL5O2ZMMORrjgRE5PbKiXgvHdQcUQ=", validate=True
)
_PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True, slots=True)
class WindowsCloudBundle:
    delivery_directory: Path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    payload: dict[str, object] = {}
    for key, value in pairs:
        if key in payload:
            raise ValueError("Windows cloud approval has duplicate fields")
        payload[key] = value
    return payload


def _absolute(path: Path) -> Path:
    return Path(path).expanduser().absolute()


def _is_reparse_point(status: os.stat_result) -> bool:
    return bool(
        getattr(status, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def _require_real_directory(path: Path) -> None:
    try:
        status = path.lstat()
    except OSError as exc:
        raise ValueError("Windows cloud delivery tree is invalid") from exc
    if path.is_symlink() or _is_reparse_point(status) or not stat.S_ISDIR(status.st_mode):
        raise ValueError("Windows cloud delivery tree is invalid")


def _require_regular_file(path: Path) -> None:
    try:
        status = path.lstat()
    except OSError as exc:
        raise ValueError("Windows cloud delivery tree is invalid") from exc
    if path.is_symlink() or _is_reparse_point(status) or not stat.S_ISREG(status.st_mode):
        raise ValueError("Windows cloud delivery tree is invalid")


def _require_exact_delivery_tree(delivery_directory: Path) -> Path:
    destination = _absolute(delivery_directory)
    _require_real_directory(destination)
    try:
        top_level = {entry.name for entry in destination.iterdir()}
    except OSError as exc:
        raise ValueError("Windows cloud delivery tree is invalid") from exc
    if top_level != _DELIVERY_FILES | {"public-cloud-defaults"}:
        raise ValueError("Windows cloud delivery tree is invalid")
    for name in _DELIVERY_FILES:
        _require_regular_file(destination / name)
    resources = destination / "public-cloud-defaults"
    _require_real_directory(resources)
    expected = {CONFIG_NAME, CA_BUNDLE_NAME, LICENSE_PUBLIC_KEY_NAME}
    try:
        names = {entry.name for entry in resources.iterdir()}
    except OSError as exc:
        raise ValueError("Windows cloud delivery tree is invalid") from exc
    if names != expected:
        raise ValueError("Windows cloud delivery tree is invalid")
    for name in expected:
        _require_regular_file(resources / name)
    return destination


def _read_signature(path: Path) -> bytes:
    try:
        encoded = path.read_text(encoding="ascii").strip()
        signature = base64.b64decode(encoded, validate=True)
    except (OSError, UnicodeDecodeError, binascii.Error) as exc:
        raise ValueError("Windows cloud approval signature is invalid") from exc
    if len(signature) != 64:
        raise ValueError("Windows cloud approval signature is invalid")
    return signature


def _read_verified_approval(approval_file: Path, signature_file: Path) -> dict[str, object]:
    try:
        raw_approval = approval_file.read_bytes()
    except OSError as exc:
        raise ValueError("Windows cloud approval is invalid") from exc
    try:
        Ed25519PublicKey.from_public_bytes(_TRUSTED_APPROVAL_PUBLIC_KEY).verify(
            _read_signature(signature_file), raw_approval
        )
    except InvalidSignature as exc:
        raise ValueError("Windows cloud approval signature is invalid") from exc
    try:
        payload = json.loads(
            raw_approval.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError("Windows cloud approval is invalid") from exc
    if not isinstance(payload, dict) or set(payload) != _APPROVAL_FIELDS:
        raise ValueError("Windows cloud approval has an invalid schema")
    if payload["schema_version"] != APPROVAL_SCHEMA:
        raise ValueError("Windows cloud approval has an invalid schema")
    if payload["approval_state"] != "approved":
        raise ValueError("Windows cloud approval is not approved")
    for field in ("source", "approved_by", "approved_at", "environment", "target_commit"):
        if not isinstance(payload[field], str):
            raise ValueError("Windows cloud approval has invalid values")
    if not payload["source"].strip() or not payload["approved_by"].strip():
        raise ValueError("Windows cloud approval requires source and approver")
    try:
        datetime.fromisoformat(payload["approved_at"].replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Windows cloud approval has an invalid timestamp") from exc
    if payload["environment"] != "integration":
        raise ValueError("Windows cloud approval must target integration")
    if not _COMMIT_PATTERN.fullmatch(payload["target_commit"]):
        raise ValueError("Windows cloud approval requires a full target commit")
    config = payload["config"]
    files = payload["files"]
    if not isinstance(config, dict) or set(config) != _CONFIG_FIELDS:
        raise ValueError("Windows cloud approval has an invalid config")
    if not all(isinstance(value, str) for value in config.values()):
        raise ValueError("Windows cloud approval has an invalid config")
    if config["channel"] != "integration":
        raise ValueError("Windows cloud approval must target integration")
    if not isinstance(files, dict) or set(files) != _RESOURCE_FILES:
        raise ValueError("Windows cloud approval has invalid file digests")
    if not all(
        isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest)
        for digest in files.values()
    ):
        raise ValueError("Windows cloud approval has invalid file digests")
    return payload


def _require_clean_target_project(project_root: Path, target_commit: str) -> Path:
    root = _absolute(project_root)
    _require_real_directory(root)
    try:
        head = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        changes = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain=v1", "--untracked-files=all"],
            check=True, capture_output=True, text=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError("Windows cloud source project root is not a Git worktree") from exc
    if changes:
        raise ValueError("Windows cloud source project root must be clean")
    if head != target_commit:
        raise ValueError("Windows cloud source target commit does not match approval")
    return root


def _integration_defaults(directory: Path) -> PackagedCloudDefaults:
    defaults = load_packaged_cloud_defaults(directory)
    if defaults is None:
        raise ValueError("cloud default source must contain cloud-default.json")
    if not defaults.integration_mode:
        raise ValueError("Windows cloud delivery only supports integration")
    try:
        ssl.create_default_context(cafile=str(defaults.ca_bundle))
    except ssl.SSLError as exc:
        raise ValueError("cloud CA bundle is invalid") from exc
    return defaults


def _approved_config(defaults: PackagedCloudDefaults) -> dict[str, str]:
    return {
        "api_base_url": defaults.base_url,
        "channel": "integration",
        "license_key_id": defaults.license_key_id,
    }


def _approved_file_digests(directory: Path) -> dict[str, str]:
    return {
        f"public-cloud-defaults/{CONFIG_NAME}": _sha256(directory / CONFIG_NAME),
        f"public-cloud-defaults/{CA_BUNDLE_NAME}": _sha256(directory / CA_BUNDLE_NAME),
        f"public-cloud-defaults/{LICENSE_PUBLIC_KEY_NAME}": _sha256(directory / LICENSE_PUBLIC_KEY_NAME),
    }


def _resource_bytes(directory: Path) -> dict[str, bytes]:
    return {
        f"public-cloud-defaults/{CONFIG_NAME}": (directory / CONFIG_NAME).read_bytes(),
        f"public-cloud-defaults/{CA_BUNDLE_NAME}": (directory / CA_BUNDLE_NAME).read_bytes(),
        f"public-cloud-defaults/{LICENSE_PUBLIC_KEY_NAME}": (
            directory / LICENSE_PUBLIC_KEY_NAME
        ).read_bytes(),
    }


def _resource_digests(resources: dict[str, bytes]) -> dict[str, str]:
    return {
        relative_path: hashlib.sha256(payload).hexdigest()
        for relative_path, payload in resources.items()
    }


def _write_local_resources(directory: Path, resources: dict[str, bytes]) -> Path:
    destination = _absolute(directory)
    if destination.exists():
        raise FileExistsError("Windows cloud local runtime directory already exists")
    destination.mkdir(mode=0o700, parents=True)
    for relative_path, payload in resources.items():
        file = destination / Path(relative_path).name
        file.write_bytes(payload)
        os.chmod(file, 0o600)
    return destination


def _require_approval_matches_inputs(
    approval: dict[str, object], defaults: PackagedCloudDefaults, directory: Path
) -> None:
    if approval["config"] != _approved_config(defaults):
        raise ValueError("Windows cloud approval does not match public defaults")
    if approval["files"] != _approved_file_digests(directory):
        raise ValueError("Windows cloud approval does not match public defaults")


def _validated_delivery_inputs(
    delivery_directory: Path, project_root: Path
) -> tuple[Path, dict[str, object], dict[str, bytes], PackagedCloudDefaults]:
    destination = _require_exact_delivery_tree(delivery_directory)
    approval = _read_verified_approval(
        destination / "approval.json", destination / "approval.sig"
    )
    resources = _resource_bytes(destination / "public-cloud-defaults")
    if approval["files"] != _resource_digests(resources):
        raise ValueError("Windows cloud approval does not match public defaults")
    with tempfile.TemporaryDirectory(prefix="feetforceplate-r321-verify-") as staging:
        staged = _write_local_resources(Path(staging) / "resources", resources)
        defaults = _integration_defaults(staged)
        _require_approval_matches_inputs(approval, defaults, staged)
    _require_clean_target_project(project_root, str(approval["target_commit"]))
    return destination, approval, resources, defaults


def prepare_windows_cloud_default_bundle(
    *, source_directory: Path, approval_file: Path, approval_signature_file: Path,
    delivery_directory: Path, project_root: Path = _PROJECT_ROOT,
) -> WindowsCloudBundle:
    """Create a new signed R2 delivery without overwriting historical evidence."""

    source = _absolute(source_directory)
    defaults = _integration_defaults(source)
    approval = _read_verified_approval(approval_file, approval_signature_file)
    _require_approval_matches_inputs(approval, defaults, source)
    _require_clean_target_project(project_root, str(approval["target_commit"]))
    destination = _absolute(delivery_directory)
    try:
        destination.lstat()
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise ValueError("Windows cloud delivery path is invalid") from exc
    else:
        raise FileExistsError("Windows cloud delivery directory already exists")
    resources = destination / "public-cloud-defaults"
    resources.mkdir(parents=True)
    shutil.copyfile(approval_file, destination / "approval.json")
    shutil.copyfile(approval_signature_file, destination / "approval.sig")
    for name in (CONFIG_NAME, CA_BUNDLE_NAME, LICENSE_PUBLIC_KEY_NAME):
        shutil.copyfile(source / name, resources / name)
    _require_exact_delivery_tree(destination)
    return WindowsCloudBundle(delivery_directory=destination)


def validate_windows_cloud_default_bundle(
    delivery_directory: Path, *, project_root: Path = _PROJECT_ROOT
) -> PackagedCloudDefaults:
    """Fail closed unless R2 delivery matches clean controlled source."""

    destination, _approval, _resources, defaults = _validated_delivery_inputs(
        delivery_directory, project_root
    )
    return PackagedCloudDefaults(
        base_url=defaults.base_url,
        integration_mode=defaults.integration_mode,
        license_key_id=defaults.license_key_id,
        ca_bundle=destination / "public-cloud-defaults" / CA_BUNDLE_NAME,
        license_public_key=destination / "public-cloud-defaults" / LICENSE_PUBLIC_KEY_NAME,
    )


def materialize_validated_windows_cloud_runtime(
    delivery_directory: Path, *, project_root: Path = _PROJECT_ROOT, runtime_directory: Path
) -> PackagedCloudDefaults:
    """Stage the verified bytes locally so launch never rereads mutable sync files."""

    _destination, approval, resources, _defaults = _validated_delivery_inputs(
        delivery_directory, project_root
    )
    staged = _write_local_resources(runtime_directory, resources)
    defaults = _integration_defaults(staged)
    _require_approval_matches_inputs(approval, defaults, staged)
    return defaults


__all__ = [
    "APPROVAL_SCHEMA", "WindowsCloudBundle", "prepare_windows_cloud_default_bundle",
    "materialize_validated_windows_cloud_runtime", "validate_windows_cloud_default_bundle",
]
