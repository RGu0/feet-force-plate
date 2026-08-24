from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from techflex_cloud_foundation import (
    AuthorizedTransport,
    EntitlementDecision,
    OperationState,
    ReliableOperation,
    RetryPolicy,
    SecureTransport,
    SqliteOperationStore,
    TrustBundle,
    TrustBundleVerifier,
)


class _Tokens:
    def __init__(self) -> None:
        self.value = "first"
        self.refresh_count = 0

    def current_access_token(self) -> str:
        return self.value

    def refresh(self) -> None:
        self.refresh_count += 1
        self.value = "second"


def test_independent_consumer_uses_only_public_api(tmp_path: Path) -> None:
    store = SqliteOperationStore(tmp_path / "operations.sqlite3")
    operation = ReliableOperation.create(
        kind="example.upload",
        payload_ref="spool/session-1",
        payload_digest="a" * 64,
        idempotency_key="example:session-1",
    )

    store.enqueue(operation)

    assert store.lease_due(now=datetime.now(UTC)) == operation


def test_retry_policy_keeps_server_retry_after_deadline() -> None:
    policy = RetryPolicy(base_delay=timedelta(seconds=5), cap_delay=timedelta(minutes=5))
    now = datetime(2026, 8, 24, tzinfo=UTC)

    assert policy.next_attempt_at(
        now=now,
        attempt_count=3,
        retry_after=timedelta(seconds=90),
    ) == now + timedelta(seconds=90)


def test_authorized_transport_refreshes_at_most_once_after_401() -> None:
    seen: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("Authorization"))
        if request.headers.get("Authorization") == "Bearer first":
            return httpx.Response(401, request=request)
        return httpx.Response(200, json={"ok": True}, request=request)

    tokens = _Tokens()
    with SecureTransport(
        "https://foundation.test",
        transport=httpx.MockTransport(handler),
    ) as transport:
        response = AuthorizedTransport(transport, tokens).request("GET", "/v1/check")

    assert response.status_code == 200
    assert tokens.refresh_count == 1
    assert seen == ["Bearer first", "Bearer second"]


def test_trust_bundle_requires_root_signature_and_monotonic_revision() -> None:
    root = Ed25519PrivateKey.generate()
    bundle = TrustBundle(
        revision=2,
        issued_at=datetime(2026, 8, 24, tzinfo=UTC),
        signing_keys={"license/2": b"x" * 32},
        revoked_key_ids=("license/1",),
        policy={"screening.start": True},
    )
    signed = bundle.sign(root)

    verified = TrustBundleVerifier(root.public_key().public_bytes_raw()).verify(
        signed,
        minimum_revision=1,
    )

    assert verified.revision == 2
    with pytest.raises(ValueError, match="revision"):
        TrustBundleVerifier(root.public_key().public_bytes_raw()).verify(
            signed,
            minimum_revision=2,
        )


def test_entitlement_decision_is_immutable_and_application_scoped() -> None:
    decision = EntitlementDecision(
        license_id=UUID("00000000-0000-0000-0000-000000000001"),
        application_id="feetforceplate",
        capabilities=frozenset({"screening.start"}),
        policy_revision=3,
        evaluated_at=datetime(2026, 8, 24, tzinfo=UTC),
    )

    assert decision.allows("screening.start")
    assert not decision.allows("report.export")
    with pytest.raises((AttributeError, TypeError)):
        decision.application_id = "other"  # type: ignore[misc]


def test_operation_store_recovers_only_interrupted_leases(tmp_path: Path) -> None:
    store = SqliteOperationStore(tmp_path / "operations.sqlite3")
    operation = ReliableOperation.create(
        kind="example.upload",
        payload_ref="spool/session-2",
        payload_digest="b" * 64,
        idempotency_key="example:session-2",
    )
    store.enqueue(operation)
    leased = store.lease_due(now=datetime.now(UTC))
    assert leased is not None

    store.recover_interrupted_leases(now=datetime.now(UTC))

    assert store.get(operation.operation_id).state is OperationState.READY
