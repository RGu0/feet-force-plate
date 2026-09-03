from __future__ import annotations

import base64
import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
import subprocess
import sys

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.x509.oid import NameOID
import pytest

import client.cloud.windows_bundle as windows_bundle


def _run_git(directory: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(directory), *arguments],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _clean_project_root(directory: Path) -> tuple[Path, str]:
    directory.mkdir()
    _run_git(directory, "init", "-q")
    _run_git(directory, "config", "user.email", "tests@example.invalid")
    _run_git(directory, "config", "user.name", "RAY-321 tests")
    (directory / "source-marker.txt").write_text("clean source\n", encoding="utf-8")
    _run_git(directory, "add", "source-marker.txt")
    _run_git(directory, "commit", "-q", "-m", "trusted source")
    return directory, _run_git(directory, "rev-parse", "HEAD")


def _write_public_inputs(source: Path, *, channel: str = "integration") -> None:
    source.mkdir()
    endpoint = (
        "https://39.105.216.113:7443"
        if channel == "integration"
        else "https://distribution.example.test"
    )
    (source / "cloud-default.json").write_text(
        json.dumps(
            {
                "schema_version": "feetforceplate-client-cloud-default/1",
                "channel": channel,
                "api_base_url": endpoint,
                "license_key_id": "license/1",
                "ca_bundle_resource": "cloud-ca.pem",
                "license_public_key_resource": "license-public.key",
            }
        ),
        encoding="utf-8",
    )
    private_key = Ed25519PrivateKey.generate()
    subject = issuer = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, "FeetForcePlate integration CA")]
    )
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(UTC) - timedelta(days=1))
        .not_valid_after(datetime.now(UTC) + timedelta(days=1))
        .sign(private_key, algorithm=None)
    )
    (source / "cloud-ca.pem").write_bytes(
        certificate.public_bytes(serialization.Encoding.PEM)
    )
    (source / "license-public.key").write_bytes(b"p" * 32)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _approval_payload(source: Path, target_commit: str) -> dict[str, object]:
    config = json.loads((source / "cloud-default.json").read_text(encoding="utf-8"))
    return {
        "schema_version": "feetforceplate-windows-cloud-approval/2",
        "approval_state": "approved",
        "source": "License service public export",
        "approved_by": "License service owner",
        "approved_at": "2026-09-02T00:00:00Z",
        "environment": "integration",
        "target_commit": target_commit,
        "config": {
            "api_base_url": config["api_base_url"],
            "channel": config["channel"],
            "license_key_id": config["license_key_id"],
        },
        "files": {
            "public-cloud-defaults/cloud-ca.pem": _sha256(source / "cloud-ca.pem"),
            "public-cloud-defaults/cloud-default.json": _sha256(
                source / "cloud-default.json"
            ),
            "public-cloud-defaults/license-public.key": _sha256(
                source / "license-public.key"
            ),
        },
    }


def _write_signed_approval(
    source: Path,
    *,
    target_commit: str,
    signing_key: Ed25519PrivateKey,
) -> tuple[Path, Path]:
    approval = source / "approval.json"
    approval.write_text(
        json.dumps(_approval_payload(source, target_commit), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    signature = source / "approval.sig"
    signature.write_text(
        base64.b64encode(signing_key.sign(approval.read_bytes())).decode("ascii")
        + "\n",
        encoding="ascii",
    )
    return approval, signature


def _prepare_signed_delivery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path, Path]:
    project_root, target_commit = _clean_project_root(tmp_path / "project")
    source = tmp_path / "public-inputs"
    _write_public_inputs(source)
    signing_key = Ed25519PrivateKey.generate()
    monkeypatch.setattr(
        windows_bundle,
        "_TRUSTED_APPROVAL_PUBLIC_KEY",
        signing_key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        ),
    )
    approval, signature = _write_signed_approval(
        source, target_commit=target_commit, signing_key=signing_key
    )
    delivery = tmp_path / "delivery"
    windows_bundle.prepare_windows_cloud_default_bundle(
        source_directory=source,
        approval_file=approval,
        approval_signature_file=signature,
        delivery_directory=delivery,
        project_root=project_root,
    )
    return project_root, source, delivery


def test_signed_delivery_uses_only_approved_integration_resources_and_clean_target_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_root, _source, delivery = _prepare_signed_delivery(tmp_path, monkeypatch)

    settings = windows_bundle.validate_windows_cloud_default_bundle(
        delivery, project_root=project_root
    )

    assert settings.base_url == "https://39.105.216.113:7443"
    assert settings.integration_mode is True
    assert {item.relative_to(delivery).as_posix() for item in delivery.rglob("*")} == {
        "approval.json",
        "approval.sig",
        "public-cloud-defaults",
        "public-cloud-defaults/cloud-ca.pem",
        "public-cloud-defaults/cloud-default.json",
        "public-cloud-defaults/license-public.key",
    }


def test_recomputed_approval_file_hashes_still_fail_without_a_new_owner_signature(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_root, _source, delivery = _prepare_signed_delivery(tmp_path, monkeypatch)
    approval = json.loads((delivery / "approval.json").read_text(encoding="utf-8"))
    altered_config = delivery / "public-cloud-defaults" / "cloud-default.json"
    altered_config.write_text(
        altered_config.read_text(encoding="utf-8").replace("license/1", "license/2"),
        encoding="utf-8",
    )
    approval["files"]["public-cloud-defaults/cloud-default.json"] = _sha256(
        altered_config
    )
    approval["config"]["license_key_id"] = "license/2"
    (delivery / "approval.json").write_text(
        json.dumps(approval, sort_keys=True) + "\n", encoding="utf-8"
    )

    with pytest.raises(ValueError, match="approval signature"):
        windows_bundle.validate_windows_cloud_default_bundle(
            delivery, project_root=project_root
        )


def test_delivery_rejects_extra_items_and_symbolic_links(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_root, _source, delivery = _prepare_signed_delivery(tmp_path, monkeypatch)
    (delivery / "untrusted-launcher.ps1").write_text("Write-Host unsafe\n")

    with pytest.raises(ValueError, match="tree"):
        windows_bundle.validate_windows_cloud_default_bundle(
            delivery, project_root=project_root
        )

    (delivery / "untrusted-launcher.ps1").unlink()
    (delivery / "public-cloud-defaults" / "license-public.key").unlink()
    os.symlink(
        delivery / "public-cloud-defaults" / "cloud-ca.pem",
        delivery / "public-cloud-defaults" / "license-public.key",
    )

    with pytest.raises(ValueError, match="tree"):
        windows_bundle.validate_windows_cloud_default_bundle(
            delivery, project_root=project_root
        )


def test_delivery_rejects_changed_or_dirty_source_project_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_root, _source, delivery = _prepare_signed_delivery(tmp_path, monkeypatch)
    (project_root / "source-marker.txt").write_text("dirty source\n", encoding="utf-8")

    with pytest.raises(ValueError, match="clean"):
        windows_bundle.validate_windows_cloud_default_bundle(
            delivery, project_root=project_root
        )
    _run_git(project_root, "add", "source-marker.txt")
    _run_git(project_root, "commit", "-q", "-m", "different commit")
    with pytest.raises(ValueError, match="target commit"):
        windows_bundle.validate_windows_cloud_default_bundle(
            delivery, project_root=project_root
        )


def test_materialized_launch_settings_do_not_reread_mutable_sync_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_root, _source, delivery = _prepare_signed_delivery(tmp_path, monkeypatch)
    local_runtime = tmp_path / "local-runtime"

    settings = windows_bundle.materialize_validated_windows_cloud_runtime(
        delivery, project_root=project_root, runtime_directory=local_runtime
    )
    original_ca = settings.ca_bundle.read_bytes()
    original_key = settings.license_public_key.read_bytes()
    (delivery / "public-cloud-defaults" / "cloud-ca.pem").write_text(
        "attacker CA", encoding="utf-8"
    )
    (delivery / "public-cloud-defaults" / "license-public.key").write_bytes(
        b"q" * 32
    )

    assert settings.ca_bundle.read_bytes() == original_ca
    assert settings.license_public_key.read_bytes() == original_key


def test_direct_cli_rejects_a_project_root_other_than_its_controlled_checkout(
    tmp_path: Path,
) -> None:
    command = Path(__file__).parents[2] / "scripts" / "windows_cloud_default_bundle.py"
    completed = subprocess.run(
        [
            sys.executable,
            str(command),
            "validate",
            "--delivery",
            str(tmp_path / "delivery"),
            "--project-root",
            str(tmp_path / "untrusted-project"),
        ],
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "controlled source root" in completed.stderr


def test_prepare_rejects_distribution_even_when_generic_packaging_accepts_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_root, target_commit = _clean_project_root(tmp_path / "project")
    source = tmp_path / "public-inputs"
    _write_public_inputs(source, channel="distribution")
    signing_key = Ed25519PrivateKey.generate()
    monkeypatch.setattr(
        windows_bundle,
        "_TRUSTED_APPROVAL_PUBLIC_KEY",
        signing_key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        ),
    )
    approval, signature = _write_signed_approval(
        source, target_commit=target_commit, signing_key=signing_key
    )

    with pytest.raises(ValueError, match="integration"):
        windows_bundle.prepare_windows_cloud_default_bundle(
            source_directory=source,
            approval_file=approval,
            approval_signature_file=signature,
            delivery_directory=tmp_path / "delivery",
            project_root=project_root,
        )
