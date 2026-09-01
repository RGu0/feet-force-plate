import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.x509.oid import NameOID

from client.cloud.windows_bundle import (
    prepare_windows_cloud_default_bundle,
    validate_windows_cloud_default_bundle,
)


def _write_public_inputs(source: Path) -> Path:
    source.mkdir()
    (source / "cloud-default.json").write_text(
        json.dumps(
            {
                "schema_version": "feetforceplate-client-cloud-default/1",
                "channel": "integration",
                "api_base_url": "https://39.105.216.113:7443",
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
    approval = source / "approval.json"
    approval.write_text(
        json.dumps(
            {
                "schema_version": "feetforceplate-windows-cloud-approval/1",
                "approval_state": "approved",
                "source": "License service public export",
                "approved_by": "License service owner",
                "approved_at": "2026-08-31T00:00:00Z",
                "environment": "integration",
                "target_commit": "a" * 40,
            }
        ),
        encoding="utf-8",
    )
    return approval


def test_prepare_windows_bundle_copies_approved_public_inputs_with_a_manifest(
    tmp_path: Path,
) -> None:
    source = tmp_path / "approved-public-export"
    approval = _write_public_inputs(source)
    delivery = tmp_path / "synced-delivery"

    result = prepare_windows_cloud_default_bundle(
        source_directory=source,
        approval_file=approval,
        delivery_directory=delivery,
    )

    manifest = json.loads((delivery / "bundle-manifest.json").read_text("utf-8"))
    assert result.delivery_directory == delivery
    assert manifest["approval"]["approval_state"] == "approved"
    assert manifest["config"] == {
        "api_base_url": "https://39.105.216.113:7443",
        "channel": "integration",
        "license_key_id": "license/1",
    }
    assert set(manifest["files"]) == {
        "approval.json",
        "Invoke-FeetForcePlateCloudClient.ps1",
        "README.md",
        "public-cloud-defaults/cloud-ca.pem",
        "public-cloud-defaults/cloud-default.json",
        "public-cloud-defaults/license-public.key",
    }
    assert not (delivery / "license-private.key").exists()
    assert (
        delivery / "public-cloud-defaults" / "license-public.key"
    ).read_bytes() == b"p" * 32
    assert (delivery / "Invoke-FeetForcePlateCloudClient.ps1").is_file()
    assert (delivery / "README.md").is_file()


def test_validate_windows_bundle_rejects_a_synchronized_public_key_change(
    tmp_path: Path,
) -> None:
    source = tmp_path / "approved-public-export"
    approval = _write_public_inputs(source)
    delivery = tmp_path / "synced-delivery"
    prepare_windows_cloud_default_bundle(
        source_directory=source,
        approval_file=approval,
        delivery_directory=delivery,
    )
    (delivery / "public-cloud-defaults" / "license-public.key").write_bytes(
        b"q" * 32
    )

    try:
        validate_windows_cloud_default_bundle(delivery)
    except ValueError as error:
        assert str(error) == "Windows cloud delivery digest mismatch"
    else:
        raise AssertionError("altered synced bundle was accepted")


def test_windows_bundle_validation_command_emits_only_launch_settings(
    tmp_path: Path,
) -> None:
    source = tmp_path / "approved-public-export"
    approval = _write_public_inputs(source)
    delivery = tmp_path / "synced-delivery"
    prepare_windows_cloud_default_bundle(
        source_directory=source,
        approval_file=approval,
        delivery_directory=delivery,
    )
    command = Path(__file__).parents[2] / "scripts" / "windows_cloud_default_bundle.py"

    completed = subprocess.run(
        [sys.executable, str(command), "validate", "--delivery", str(delivery)],
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {
        "api_base_url": "https://39.105.216.113:7443",
        "ca_bundle": str(delivery / "public-cloud-defaults" / "cloud-ca.pem"),
        "integration_mode": True,
        "license_key_id": "license/1",
        "license_public_key_file": str(
            delivery / "public-cloud-defaults" / "license-public.key"
        ),
    }
    assert "pppp" not in completed.stdout
