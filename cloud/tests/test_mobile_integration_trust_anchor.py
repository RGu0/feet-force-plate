from __future__ import annotations

import hashlib
import json
import ssl
from pathlib import Path

ANCHOR = Path(__file__).resolve().parents[2] / "release" / "mobile-integration-trust-anchor"
EXPECTED_FILES = {"cloud-ca.pem", "cloud-default.json", "license-public.key"}


def test_bundle_contains_only_the_three_public_files() -> None:
    names = {path.name for path in ANCHOR.iterdir()}
    assert names == EXPECTED_FILES | {"README.md", "SHA256SUMS"}


def test_sha256sums_match_files() -> None:
    listed = {}
    for line in (ANCHOR / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        digest, name = line.split()
        listed[name] = digest
    assert set(listed) == EXPECTED_FILES
    for name, digest in listed.items():
        assert hashlib.sha256((ANCHOR / name).read_bytes()).hexdigest() == digest


def test_license_key_is_raw_ed25519_public_key() -> None:
    key = (ANCHOR / "license-public.key").read_bytes()
    assert len(key) == 32
    assert hashlib.sha256(key).hexdigest().startswith("40b50ea2")


def test_config_is_integration_only_with_license_key_id() -> None:
    config = json.loads((ANCHOR / "cloud-default.json").read_text(encoding="utf-8"))
    assert config["channel"] == "integration"
    assert config["license_key_id"] == "license/1"
    assert config["api_base_url"].endswith(":7443")
    assert config["api_base_url"].startswith("https://")


def test_ca_is_a_single_public_certificate() -> None:
    pem = (ANCHOR / "cloud-ca.pem").read_text(encoding="utf-8")
    assert pem.count("BEGIN CERTIFICATE") == 1
    ssl.PEM_cert_to_DER_cert(pem)


def test_bundle_has_no_private_key_material() -> None:
    for path in ANCHOR.iterdir():
        assert "PRIVATE KEY" not in path.read_text(encoding="utf-8", errors="ignore")
