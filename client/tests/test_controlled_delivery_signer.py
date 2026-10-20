from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
import subprocess
import sys

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.x509.oid import NameOID

import client.cloud.controlled_delivery_signer as signer
import client.cloud.windows_bundle as windows_bundle


def _git(directory: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(directory), *arguments], check=True, capture_output=True, text=True
    )
    return completed.stdout.strip()


def _clean_project(directory: Path) -> tuple[Path, str]:
    directory.mkdir()
    _git(directory, "init", "-q")
    _git(directory, "config", "user.email", "tests@example.invalid")
    _git(directory, "config", "user.name", "RAY-448 tests")
    (directory / "source-marker.txt").write_text("clean source\n", encoding="utf-8")
    _git(directory, "add", "source-marker.txt")
    _git(directory, "commit", "-q", "-m", "trusted source")
    return directory, _git(directory, "rev-parse", "HEAD")


def _public_source(directory: Path) -> Path:
    directory.mkdir()
    (directory / "cloud-default.json").write_text(
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
    certificate_key = Ed25519PrivateKey.generate()
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "RAY-448 test CA")])
    certificate = (
        x509.CertificateBuilder().subject_name(subject).issuer_name(issuer)
        .public_key(certificate_key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(UTC) - timedelta(days=1))
        .not_valid_after(datetime.now(UTC) + timedelta(days=1)).sign(certificate_key, algorithm=None)
    )
    (directory / "cloud-ca.pem").write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    (directory / "license-public.key").write_bytes(b"p" * 32)
    return directory


def _request(directory: Path, *, target_commit: str, approved_by: str = "Release owner") -> Path:
    path = directory / "approved-request.json"
    requested_at = datetime(2026, 9, 15, 4, 0, tzinfo=UTC)
    path.write_text(
        json.dumps(
            {
                "schema_version": "feetforceplate-controlled-delivery-signing-request/1",
                "approval_state": "approved",
                "approved_by": approved_by,
                "requested_at": requested_at.isoformat().replace("+00:00", "Z"),
                "expires_at": (requested_at + timedelta(minutes=10)).isoformat().replace("+00:00", "Z"),
                "target_commit": target_commit,
            },
            sort_keys=True,
        ) + "\n",
        encoding="utf-8",
    )
    return path


def _policy(directory: Path, private_key: Ed25519PrivateKey) -> Path:
    key_file = directory / "private.key"
    key_file.write_bytes(
        private_key.private_bytes(
            serialization.Encoding.Raw,
            serialization.PrivateFormat.Raw,
            serialization.NoEncryption(),
        )
    )
    path = directory / "signer-policy.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "feetforceplate-controlled-delivery-signer-policy/1",
                "source": "RAY-448 protected offline signer",
                "approved_by": "Release owner",
                "private_key_file": str(key_file),
                "audit_log_file": str(directory / "signer-audit.jsonl"),
                "maximum_request_ttl_seconds": 900,
            },
            sort_keys=True,
        ) + "\n",
        encoding="utf-8",
    )
    return path


def _raw_public(private_key: Ed25519PrivateKey) -> bytes:
    return private_key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )


def test_signer_issues_a_verifier_accepted_pair_from_clean_source(tmp_path, monkeypatch) -> None:
    project, commit = _clean_project(tmp_path / "project")
    source = _public_source(tmp_path / "public-defaults")
    private_key = Ed25519PrivateKey.generate()
    monkeypatch.setattr(windows_bundle, "_TRUSTED_APPROVAL_PUBLIC_KEY", _raw_public(private_key))

    issued = signer.issue_approval_pair(
        request_file=_request(tmp_path, target_commit=commit),
        policy_file=_policy(tmp_path, private_key),
        source_directory=source,
        project_root=project,
        output_directory=tmp_path / "approval-pair",
        now=datetime(2026, 9, 15, 4, 1, tzinfo=UTC),
    )

    assert {entry.name for entry in issued.output_directory.iterdir()} == {"approval.json", "approval.sig"}
    assert len(base64.b64decode((issued.output_directory / "approval.sig").read_text(encoding="ascii"))) == 64
    delivery = tmp_path / "delivery"
    windows_bundle.prepare_windows_cloud_default_bundle(
        source_directory=source,
        approval_file=issued.output_directory / "approval.json",
        approval_signature_file=issued.output_directory / "approval.sig",
        delivery_directory=delivery,
        project_root=project,
    )
    assert windows_bundle.validate_windows_cloud_default_bundle(delivery, project_root=project).integration_mode

import pytest


def test_signer_rejects_unapproved_request_without_creating_delivery_output(tmp_path, monkeypatch) -> None:
    project, commit = _clean_project(tmp_path / "project")
    source = _public_source(tmp_path / "public-defaults")
    private_key = Ed25519PrivateKey.generate()
    monkeypatch.setattr(windows_bundle, "_TRUSTED_APPROVAL_PUBLIC_KEY", _raw_public(private_key))
    request = _request(tmp_path, target_commit=commit)
    payload = json.loads(request.read_text(encoding="utf-8"))
    payload["approval_state"] = "pending"
    request.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="not approved"):
        signer.issue_approval_pair(
            request_file=request, policy_file=_policy(tmp_path, private_key), source_directory=source,
            project_root=project, output_directory=tmp_path / "approval-pair",
            now=datetime(2026, 9, 15, 4, 1, tzinfo=UTC),
        )

    assert not (tmp_path / "approval-pair").exists()


@pytest.mark.parametrize("mutation", ["dirty-source", "wrong-key"], ids=["dirty-source", "wrong-key"])
def test_signer_rejections_are_audited_without_private_material(tmp_path, monkeypatch, mutation: str) -> None:
    project, commit = _clean_project(tmp_path / "project")
    source = _public_source(tmp_path / "public-defaults")
    private_key = Ed25519PrivateKey.generate()
    trusted_key = private_key if mutation == "dirty-source" else Ed25519PrivateKey.generate()
    monkeypatch.setattr(windows_bundle, "_TRUSTED_APPROVAL_PUBLIC_KEY", _raw_public(trusted_key))
    policy = _policy(tmp_path, private_key)
    if mutation == "dirty-source":
        (project / "source-marker.txt").write_text("modified\n", encoding="utf-8")

    with pytest.raises(ValueError):
        signer.issue_approval_pair(
            request_file=_request(tmp_path, target_commit=commit), policy_file=policy,
            source_directory=source, project_root=project, output_directory=tmp_path / "approval-pair",
            now=datetime(2026, 9, 15, 4, 1, tzinfo=UTC),
        )

    audit = (tmp_path / "signer-audit.jsonl").read_text(encoding="utf-8")
    assert '"operation":"approval-rejected"' in audit
    assert str(tmp_path / "private.key") not in audit
    assert private_key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()).hex() not in audit
    assert not (tmp_path / "approval-pair").exists()


def test_query_audit_returns_only_public_records_for_exact_commit(tmp_path, monkeypatch) -> None:
    project, commit = _clean_project(tmp_path / "project")
    source = _public_source(tmp_path / "public-defaults")
    private_key = Ed25519PrivateKey.generate()
    monkeypatch.setattr(windows_bundle, "_TRUSTED_APPROVAL_PUBLIC_KEY", _raw_public(private_key))
    policy = _policy(tmp_path, private_key)
    signer.issue_approval_pair(
        request_file=_request(tmp_path, target_commit=commit), policy_file=policy, source_directory=source,
        project_root=project, output_directory=tmp_path / "approval-pair",
        now=datetime(2026, 9, 15, 4, 1, tzinfo=UTC),
    )

    records = signer.query_audit(policy_file=policy, target_commit=commit)

    assert len(records) == 1
    assert records[0]["operation"] == "approval-issued"
    assert records[0]["target_commit"] == commit
    assert "private_key_file" not in records[0]


def test_signer_rejects_expired_or_oversized_requests(tmp_path, monkeypatch) -> None:
    project, commit = _clean_project(tmp_path / "project")
    source = _public_source(tmp_path / "public-defaults")
    private_key = Ed25519PrivateKey.generate()
    monkeypatch.setattr(windows_bundle, "_TRUSTED_APPROVAL_PUBLIC_KEY", _raw_public(private_key))
    request = _request(tmp_path, target_commit=commit)
    payload = json.loads(request.read_text(encoding="utf-8"))
    payload["expires_at"] = "2026-09-15T04:00:30Z"
    request.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="expired"):
        signer.issue_approval_pair(
            request_file=request, policy_file=_policy(tmp_path, private_key), source_directory=source,
            project_root=project, output_directory=tmp_path / "approval-pair",
            now=datetime(2026, 9, 15, 4, 1, tzinfo=UTC),
        )


def test_signer_cli_rejects_a_project_root_other_than_its_controlled_checkout(tmp_path) -> None:
    command = Path(__file__).parents[2] / "scripts" / "sign_windows_cloud_delivery.py"
    completed = subprocess.run(
        [
            sys.executable, str(command), "sign", "--request", str(tmp_path / "request.json"),
            "--signer-policy", str(tmp_path / "policy.json"), "--source", str(tmp_path / "source"),
            "--project-root", str(tmp_path / "another-checkout"), "--output", str(tmp_path / "output"),
        ], capture_output=True, text=True,
    )

    assert completed.returncode != 0
    assert "controlled source root" in completed.stderr


def test_signer_rejects_private_key_in_onedrive_path(tmp_path, monkeypatch) -> None:
    project, commit = _clean_project(tmp_path / "project")
    source = _public_source(tmp_path / "public-defaults")
    private_key = Ed25519PrivateKey.generate()
    monkeypatch.setattr(windows_bundle, "_TRUSTED_APPROVAL_PUBLIC_KEY", _raw_public(private_key))
    policy = _policy(tmp_path, private_key)
    protected = tmp_path / "OneDrive"
    protected.mkdir()
    key_file = protected / "private.key"
    key_file.write_bytes(
        private_key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    )
    payload = json.loads(policy.read_text(encoding="utf-8"))
    payload["private_key_file"] = str(key_file)
    policy.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="location"):
        signer.issue_approval_pair(
            request_file=_request(tmp_path, target_commit=commit), policy_file=policy, source_directory=source,
            project_root=project, output_directory=tmp_path / "approval-pair",
            now=datetime(2026, 9, 15, 4, 1, tzinfo=UTC),
        )

    assert not (tmp_path / "approval-pair").exists()
