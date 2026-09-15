"""Issue auditable Windows cloud approvals on a protected offline signer."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from . import windows_bundle


REQUEST_SCHEMA = "feetforceplate-controlled-delivery-signing-request/1"
POLICY_SCHEMA = "feetforceplate-controlled-delivery-signer-policy/1"
_REQUEST_FIELDS = {
    "schema_version", "approval_state", "approved_by", "requested_at", "expires_at", "target_commit",
}
_POLICY_FIELDS = {
    "schema_version", "source", "approved_by", "private_key_file", "audit_log_file", "maximum_request_ttl_seconds",
}
_COMMIT = re.compile(r"[0-9a-f]{40}")


@dataclass(frozen=True, slots=True)
class IssuedApproval:
    output_directory: Path
    approval_sha256: str


@dataclass(frozen=True, slots=True)
class _Policy:
    source: str
    approved_by: str
    private_key_file: Path
    audit_log_file: Path
    maximum_request_ttl_seconds: int


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("controlled delivery signer input has duplicate fields")
        result[key] = value
    return result


def _load_json(path: Path, *, label: str) -> dict[str, object]:
    try:
        raw = Path(path).read_bytes()
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"controlled delivery signer {label} is invalid") from exc
    if not isinstance(value, dict):
        raise ValueError(f"controlled delivery signer {label} is invalid")
    return value


def _absolute(path: Path) -> Path:
    return Path(path).expanduser().absolute()


def _is_reparse_point(status: os.stat_result) -> bool:
    return bool(
        getattr(status, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def _require_regular_file(path: Path, *, label: str) -> Path:
    candidate = _absolute(path)
    try:
        status = candidate.lstat()
    except OSError as exc:
        raise ValueError(f"controlled delivery signer {label} is unavailable") from exc
    if candidate.is_symlink() or _is_reparse_point(status) or not stat.S_ISREG(status.st_mode):
        raise ValueError(f"controlled delivery signer {label} is unavailable")
    return candidate


def _parse_utc(value: object, *, label: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"controlled delivery signer {label} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"controlled delivery signer {label} is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"controlled delivery signer {label} is invalid")
    return parsed.astimezone(UTC)


def _parse_policy(policy_file: Path) -> _Policy:
    payload = _load_json(policy_file, label="policy")
    if set(payload) != _POLICY_FIELDS or payload.get("schema_version") != POLICY_SCHEMA:
        raise ValueError("controlled delivery signer policy is invalid")
    source = payload["source"]
    approved_by = payload["approved_by"]
    private_key_file = payload["private_key_file"]
    audit_log_file = payload["audit_log_file"]
    maximum = payload["maximum_request_ttl_seconds"]
    if (
        not isinstance(source, str) or not source.strip()
        or not isinstance(approved_by, str) or not approved_by.strip()
        or not isinstance(private_key_file, str) or not private_key_file
        or not isinstance(audit_log_file, str) or not audit_log_file
        or isinstance(maximum, bool) or not isinstance(maximum, int) or not 1 <= maximum <= 3600
    ):
        raise ValueError("controlled delivery signer policy is invalid")
    return _Policy(
        source=source,
        approved_by=approved_by,
        private_key_file=_absolute(Path(private_key_file)),
        audit_log_file=_absolute(Path(audit_log_file)),
        maximum_request_ttl_seconds=maximum,
    )


def _parse_request(request_file: Path, policy: _Policy, *, now: datetime) -> dict[str, object]:
    payload = _load_json(request_file, label="request")
    if set(payload) != _REQUEST_FIELDS or payload.get("schema_version") != REQUEST_SCHEMA:
        raise ValueError("controlled delivery signing request is invalid")
    if payload.get("approval_state") != "approved":
        raise ValueError("controlled delivery signing request is not approved")
    approved_by = payload.get("approved_by")
    target_commit = payload.get("target_commit")
    if approved_by != policy.approved_by or not isinstance(target_commit, str) or not _COMMIT.fullmatch(target_commit):
        raise ValueError("controlled delivery signing request is invalid")
    requested_at = _parse_utc(payload.get("requested_at"), label="request")
    expires_at = _parse_utc(payload.get("expires_at"), label="request")
    if requested_at > now or expires_at < now or expires_at <= requested_at:
        raise ValueError("controlled delivery signing request is expired")
    if (expires_at - requested_at).total_seconds() > policy.maximum_request_ttl_seconds:
        raise ValueError("controlled delivery signing request lifetime is invalid")
    return payload


def _request_digest(request_file: Path) -> str:
    try:
        return hashlib.sha256(Path(request_file).read_bytes()).hexdigest()
    except OSError:
        return "unavailable"


def _audit(policy: _Policy, record: dict[str, object]) -> None:
    destination = policy.audit_log_file
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        _require_regular_file(destination, label="audit log")
    encoded = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    with destination.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(encoded)


def _audit_record(
    *, operation: str, request_digest: str, now: datetime, target_commit: str | None = None,
    approved_by: str | None = None, reason: str | None = None, approval_sha256: str | None = None,
) -> dict[str, object]:
    record: dict[str, object] = {
        "schema_version": "feetforceplate-controlled-delivery-signer-audit/1",
        "operation": operation,
        "recorded_at": now.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "request_sha256": request_digest,
    }
    if target_commit is not None:
        record["target_commit"] = target_commit
    if approved_by is not None:
        record["approved_by"] = approved_by
    if reason is not None:
        record["reason"] = reason
    if approval_sha256 is not None:
        record["approval_sha256"] = approval_sha256
    return record


def _derive_approval(
    request: dict[str, object], policy: _Policy, source_directory: Path
) -> dict[str, object]:
    source = _absolute(source_directory)
    defaults = windows_bundle._integration_defaults(source)
    return {
        "schema_version": windows_bundle.APPROVAL_SCHEMA,
        "approval_state": "approved",
        "source": policy.source,
        "approved_by": policy.approved_by,
        "approved_at": str(request["requested_at"]),
        "environment": "integration",
        "target_commit": str(request["target_commit"]),
        "config": windows_bundle._approved_config(defaults),
        "files": windows_bundle._approved_file_digests(source),
    }


def _read_matching_private_key(policy: _Policy, *, project_root: Path) -> Ed25519PrivateKey:
    key_file = _require_regular_file(policy.private_key_file, label="private key")
    resolved_key = key_file.resolve()
    root = _absolute(project_root).resolve()
    protected_boundaries = (root, (root / ".project-context").resolve())
    if any(
        resolved_key.is_relative_to(boundary) for boundary in protected_boundaries
    ) or any(part.casefold() == "onedrive" for part in resolved_key.parts):
        raise ValueError("controlled delivery signer private key location is invalid")
    try:
        private_key = Ed25519PrivateKey.from_private_bytes(key_file.read_bytes())
        public_key = private_key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
    except (OSError, ValueError) as exc:
        raise ValueError("controlled delivery signer private key is unavailable") from exc
    if public_key != windows_bundle._TRUSTED_APPROVAL_PUBLIC_KEY:
        raise ValueError("controlled delivery signer private key does not match trust anchor")
    return private_key


def issue_approval_pair(
    *, request_file: Path, policy_file: Path, source_directory: Path, project_root: Path,
    output_directory: Path, now: datetime | None = None,
) -> IssuedApproval:
    """Sign the exact clean integration inputs using an explicitly provisioned key."""

    observed_at = (now or datetime.now(UTC)).astimezone(UTC)
    request_hash = _request_digest(request_file)
    policy = _parse_policy(policy_file)
    target_commit: str | None = None
    try:
        request = _parse_request(request_file, policy, now=observed_at)
        target_commit = str(request["target_commit"])
        windows_bundle._require_clean_target_project(project_root, target_commit)
        private_key = _read_matching_private_key(policy, project_root=project_root)
        approval = _derive_approval(request, policy, source_directory)
        raw_approval = (
            json.dumps(approval, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode("utf-8")
        signature = base64.b64encode(private_key.sign(raw_approval)) + b"\n"
        destination = _absolute(output_directory)
        if destination.exists():
            raise FileExistsError("controlled delivery signer output directory already exists")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="feetforceplate-signer-", dir=destination.parent) as staging:
            staged = Path(staging)
            (staged / "approval.json").write_bytes(raw_approval)
            (staged / "approval.sig").write_bytes(signature)
            approval_sha256 = hashlib.sha256(raw_approval).hexdigest()
            _audit(policy, _audit_record(
                operation="approval-issued", request_digest=request_hash, now=observed_at,
                target_commit=target_commit, approved_by=policy.approved_by,
                approval_sha256=approval_sha256,
            ))
            staged.replace(destination)
        return IssuedApproval(output_directory=destination, approval_sha256=approval_sha256)
    except Exception as exc:
        try:
            _audit(policy, _audit_record(
                operation="approval-rejected", request_digest=request_hash, now=observed_at,
                target_commit=target_commit, reason=exc.__class__.__name__,
            ))
        except Exception:
            pass
        if isinstance(exc, (ValueError, FileExistsError)):
            raise
        raise ValueError("controlled delivery signer rejected request") from exc


def query_audit(*, policy_file: Path, target_commit: str) -> list[dict[str, object]]:
    """Return public records for one exact target commit without opening the key."""

    if not _COMMIT.fullmatch(target_commit):
        raise ValueError("controlled delivery signer target commit is invalid")
    policy = _parse_policy(policy_file)
    try:
        lines = _require_regular_file(policy.audit_log_file, label="audit log").read_text(
            encoding="utf-8"
        ).splitlines()
    except OSError as exc:
        raise ValueError("controlled delivery signer audit log is unavailable") from exc
    results: list[dict[str, object]] = []
    for line in lines:
        try:
            record = json.loads(line, object_pairs_hook=_reject_duplicate_keys)
        except (json.JSONDecodeError, ValueError) as exc:
            raise ValueError("controlled delivery signer audit log is invalid") from exc
        if not isinstance(record, dict):
            raise ValueError("controlled delivery signer audit log is invalid")
        if record.get("target_commit") == target_commit:
            results.append(record)
    return results
