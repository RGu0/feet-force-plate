"""Strict, public-only cloud defaults for a packaged desktop client."""

from __future__ import annotations

import base64
import binascii
import json
import os
import shutil
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


SCHEMA_VERSION = "feetforceplate-client-cloud-default/1"
CONFIG_NAME = "cloud-default.json"
CA_BUNDLE_NAME = "cloud-ca.pem"
LICENSE_PUBLIC_KEY_NAME = "license-public.key"
_CONFIG_FIELDS = {
    "schema_version",
    "channel",
    "api_base_url",
    "license_key_id",
    "ca_bundle_resource",
    "license_public_key_resource",
}


@dataclass(frozen=True, slots=True)
class PackagedCloudDefaults:
    base_url: str
    integration_mode: bool
    license_key_id: str
    ca_bundle: Path
    license_public_key: Path


def _read_file(directory: Path, name: str) -> Path:
    resource = directory / name
    if resource.is_symlink() or not resource.is_file():
        raise ValueError(f"packaged cloud resource {name} must be a regular file")
    return resource


def _valid_public_key(resource: Path) -> None:
    payload = resource.read_bytes()
    if len(payload) == 32:
        return
    try:
        textual_payload = payload.decode("ascii").strip()
        payload = base64.b64decode(textual_payload, validate=True)
    except (UnicodeDecodeError, binascii.Error) as exc:
        raise ValueError("License public key file is invalid") from exc
    if len(payload) != 32:
        raise ValueError("License public key must contain 32 raw bytes")


def load_packaged_cloud_defaults(directory: Path) -> PackagedCloudDefaults | None:
    """Load a validated fixed-name public bundle, or ``None`` when not packaged."""

    if not directory.exists() or not (directory / CONFIG_NAME).exists():
        return None
    config_file = _read_file(directory, CONFIG_NAME)
    try:
        payload = json.loads(config_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("packaged cloud configuration must be valid JSON") from exc
    if not isinstance(payload, dict) or set(payload) != _CONFIG_FIELDS:
        raise ValueError("packaged cloud configuration has an invalid schema")
    if payload["schema_version"] != SCHEMA_VERSION:
        raise ValueError("packaged cloud configuration has an invalid schema")
    if payload["ca_bundle_resource"] != CA_BUNDLE_NAME:
        raise ValueError("packaged cloud configuration has an invalid CA resource")
    if payload["license_public_key_resource"] != LICENSE_PUBLIC_KEY_NAME:
        raise ValueError("packaged cloud configuration has an invalid License resource")
    channel = payload["channel"]
    base_url = payload["api_base_url"]
    license_key_id = payload["license_key_id"]
    if not isinstance(channel, str) or channel not in {"integration", "distribution"}:
        raise ValueError("packaged cloud configuration has an invalid channel")
    if not isinstance(base_url, str) or not isinstance(license_key_id, str):
        raise ValueError("packaged cloud configuration has invalid values")
    if any(
        unicodedata.category(character) in {"Cc", "Zl", "Zp"}
        for value in (base_url, license_key_id)
        for character in value
    ):
        raise ValueError("packaged cloud configuration contains unsafe characters")
    parsed = urlparse(base_url)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("packaged cloud API endpoint has an invalid port") from exc
    if parsed.scheme.lower() != "https" or not parsed.netloc:
        raise ValueError("packaged cloud API endpoint must use HTTPS")
    if channel == "integration" and port != 7443:
        raise ValueError("integration bundle must use explicit port 7443")
    if channel == "distribution" and port not in (None, 443):
        raise ValueError("distribution bundle must use the standard HTTPS port")
    ca_bundle = _read_file(directory, CA_BUNDLE_NAME)
    public_key = _read_file(directory, LICENSE_PUBLIC_KEY_NAME)
    if not license_key_id.strip():
        raise ValueError("packaged cloud configuration requires a License key ID")
    _valid_public_key(public_key)
    return PackagedCloudDefaults(
        base_url=base_url.rstrip("/"),
        integration_mode=channel == "integration",
        license_key_id=license_key_id.strip(),
        ca_bundle=ca_bundle,
        license_public_key=public_key,
    )


def stage_packaged_cloud_defaults(
    source_directory: Path, destination_directory: Path
) -> None:
    """Validate and stage only the public runtime artifacts at fixed basenames."""

    source = source_directory.resolve()
    if load_packaged_cloud_defaults(source) is None:
        raise ValueError("cloud default directory must contain cloud-default.json")
    destination_directory.mkdir(parents=True, exist_ok=True)
    for name in (CONFIG_NAME, CA_BUNDLE_NAME, LICENSE_PUBLIC_KEY_NAME):
        destination_file = destination_directory / name
        shutil.copyfile(source / name, destination_file)
        os.chmod(destination_file, 0o644)


__all__ = [
    "CA_BUNDLE_NAME",
    "CONFIG_NAME",
    "LICENSE_PUBLIC_KEY_NAME",
    "PackagedCloudDefaults",
    "load_packaged_cloud_defaults",
    "stage_packaged_cloud_defaults",
]
