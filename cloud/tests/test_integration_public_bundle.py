"""Regression contract for the root-run RAY-99 public integration bundle."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from client.cloud.packaged_defaults import load_packaged_cloud_defaults


ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "deploy" / "aliyun" / "seed" / "build-integration-public-bundle.sh"
_BUNDLE_ARGUMENTS = (
    "--api-base-url",
    "https://integration.test:7443",
    "--ca-cert",
    "{ca}",
    "--license-public-key",
    "{key}",
    "--license-key-id",
    "license/integration-1",
)


def _write_public_inputs(root: Path) -> tuple[Path, Path]:
    ca = root / "source-ca.pem"
    key = root / "source-license-public.key"
    ca.write_text("-----BEGIN CERTIFICATE-----\npublic test CA\n", encoding="utf-8")
    key.write_bytes(b"p" * 32)
    return ca, key


def _bundle_arguments(ca: Path, key: Path) -> tuple[str, ...]:
    return tuple(
        value.format(ca=ca, key=key) for value in _BUNDLE_ARGUMENTS
    )


def _run_bundle(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run the actual wrapper, redirecting its root-only output for this test."""

    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "FEETFORCEPLATE_PUBLIC_BUNDLE_ROOT": str(tmp_path / "published"),
        },
    )


def _require_root() -> None:
    if os.geteuid() != 0:
        pytest.skip("publication path requires root; root gate is tested separately")


def test_builds_exact_validated_integration_bundle(tmp_path: Path) -> None:
    """Catches a successful publication with wrong names or runtime metadata."""

    _require_root()
    ca, key = _write_public_inputs(tmp_path)

    result = _run_bundle(tmp_path, *_bundle_arguments(ca, key))

    assert result.returncode == 0, result.stderr
    bundle = tmp_path / "published" / "ray-99-integration"
    assert {entry.name for entry in bundle.iterdir()} == {
        "cloud-default.json",
        "cloud-ca.pem",
        "license-public.key",
    }
    assert (bundle / "cloud-ca.pem").read_bytes() == ca.read_bytes()
    assert (bundle / "license-public.key").read_bytes() == key.read_bytes()
    defaults = load_packaged_cloud_defaults(bundle)
    assert defaults is not None
    assert defaults.integration_mode is True
    assert defaults.base_url == "https://integration.test:7443"
    assert defaults.license_key_id == "license/integration-1"


def test_requires_root_without_creating_bundle(tmp_path: Path) -> None:
    """Catches a wrapper that lets an unprivileged caller publish test output."""

    if os.geteuid() == 0:
        pytest.skip("this assertion requires an unprivileged test process")
    ca, key = _write_public_inputs(tmp_path)

    result = _run_bundle(tmp_path, *_bundle_arguments(ca, key))

    assert result.returncode == 2
    assert "must run as root" in result.stderr
    assert not (tmp_path / "published").exists()


def test_rejects_existing_bundle_without_replace(tmp_path: Path) -> None:
    """Catches accidental overwrite of an already published public bundle."""

    _require_root()
    ca, key = _write_public_inputs(tmp_path)
    arguments = _bundle_arguments(ca, key)

    assert _run_bundle(tmp_path, *arguments).returncode == 0
    config = tmp_path / "published" / "ray-99-integration" / "cloud-default.json"
    original = config.read_bytes()
    second = _run_bundle(tmp_path, *arguments)

    assert second.returncode != 0
    assert config.read_bytes() == original


@pytest.mark.parametrize(
    "url",
    ["http://integration.test:7443", "https://integration.test:443"],
)
def test_rejects_non_integration_endpoint(tmp_path: Path, url: str) -> None:
    """Catches publication to a non-HTTPS or non-integration endpoint."""

    _require_root()
    ca, key = _write_public_inputs(tmp_path)
    arguments = list(_bundle_arguments(ca, key))
    arguments[1] = url

    result = _run_bundle(tmp_path, *arguments)

    assert result.returncode != 0
    assert not (tmp_path / "published" / "ray-99-integration").exists()


def test_rejects_symlink_and_invalid_public_key(tmp_path: Path) -> None:
    """Catches source indirection or an invalid license verification key."""

    _require_root()
    ca, key = _write_public_inputs(tmp_path)
    linked = tmp_path / "linked-ca.pem"
    linked.symlink_to(ca)
    result = _run_bundle(tmp_path, *_bundle_arguments(linked, key))

    assert result.returncode != 0
    key.write_bytes(b"x" * 31)
    result = _run_bundle(tmp_path, *_bundle_arguments(ca, key))

    assert result.returncode != 0
    assert not (tmp_path / "published" / "ray-99-integration").exists()


def test_rejects_empty_ca_without_publishing(tmp_path: Path) -> None:
    """Catches publication of a bundle whose trusted CA input is empty."""

    _require_root()
    ca, key = _write_public_inputs(tmp_path)
    ca.write_bytes(b"")

    result = _run_bundle(tmp_path, *_bundle_arguments(ca, key))

    assert result.returncode != 0
    assert not (tmp_path / "published" / "ray-99-integration").exists()


def test_rejects_busy_publication_lock_without_publishing(tmp_path: Path) -> None:
    """Catches concurrent publication entering the destination move sequence."""

    _require_root()
    ca, key = _write_public_inputs(tmp_path)
    published = tmp_path / "published"
    published.mkdir()
    (published / ".ray-99-integration.lock").mkdir()

    result = _run_bundle(tmp_path, *_bundle_arguments(ca, key))

    assert result.returncode != 0
    assert "already in progress" in result.stderr
    assert not (published / "ray-99-integration").exists()


@pytest.mark.parametrize("option", ["--help", "-h"])
def test_rejects_uncontracted_help_options(tmp_path: Path, option: str) -> None:
    """Catches parser expansion beyond the five contracted option names."""

    _require_root()

    result = _run_bundle(tmp_path, option)

    assert result.returncode != 0
    assert "unknown option" in result.stderr
    assert not (tmp_path / "published").exists()


def test_failed_replacement_preserves_existing_bundle(tmp_path: Path) -> None:
    """Catches replacement logic that moves a valid bundle before validation."""

    _require_root()
    ca, key = _write_public_inputs(tmp_path)
    arguments = _bundle_arguments(ca, key)

    assert _run_bundle(tmp_path, *arguments).returncode == 0
    public_key = (
        tmp_path / "published" / "ray-99-integration" / "license-public.key"
    )
    original = public_key.read_bytes()
    key.write_bytes(b"x" * 31)
    replacement = _run_bundle(tmp_path, "--replace", *_bundle_arguments(ca, key))

    assert replacement.returncode != 0
    assert public_key.read_bytes() == original
