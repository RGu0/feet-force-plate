from __future__ import annotations

from pathlib import Path

from client.spool.state_store import (
    OFFLINE_LIMIT_NS,
    PENDING_BYTE_LIMIT,
    GateReason,
    NewTestDecision,
    SensitiveBlobCodec,
    StateStore,
    ValidSegmentRecord,
)


class _KeyProvider:
    def get_key(self) -> bytes:
        return b"k" * 32


def _store(tmp_path: Path) -> StateStore:
    return StateStore(tmp_path / "state.sqlite3", SensitiveBlobCodec(_KeyProvider()))


def _commit_handoff(
    store: StateStore,
    tmp_path: Path,
    *,
    index: int,
    byte_count: int,
) -> tuple[str, Path]:
    """Register a real formal handoff while keeping its test file small."""

    session_id = f"session-{index}"
    segment_id = f"segment-{index}"
    segment_path = tmp_path / "raw" / f"{segment_id}.ffps"
    segment_path.parent.mkdir(exist_ok=True)
    segment_path.write_bytes(b"valid-small-segment")
    store.commit_valid_session(
        session_id,
        subject_uuid="subject-1",
        consent_id=None,
        versions_json=b'{"protocol":"static-balance/1"}',
        started_at_ns=index,
        ended_at_ns=index + 1,
        manifest_sha256=f"{index:064x}",
        segments=(
            ValidSegmentRecord(
                segment_id=segment_id,
                relative_path=str(segment_path.relative_to(tmp_path)),
                byte_count=byte_count,
                sealed_at_ns=index + 1,
            ),
        ),
    )
    return session_id, segment_path


def _assert_existing_work_remains_allowed(decision: NewTestDecision) -> None:
    assert not decision.allow_new_test
    assert decision.allow_current_test_finalize
    assert decision.allow_existing_report_view
    assert decision.allow_upload


def test_capacity_gate_has_exact_24_hour_boundary(tmp_path: Path) -> None:
    """Catch a strict offline boundary drifting to >= rather than >."""

    now_ns = 9_000_000_000_000
    store = _store(tmp_path)
    try:
        store.record_successful_online(now_ns - OFFLINE_LIMIT_NS)

        decision_at_24h = store.evaluate_new_test(
            now_ns=now_ns,
            free_disk_bytes=PENDING_BYTE_LIMIT + 1,
            estimated_test_bytes=0,
        )
        decision_after_24h = store.evaluate_new_test(
            now_ns=now_ns + 1,
            free_disk_bytes=PENDING_BYTE_LIMIT + 1,
            estimated_test_bytes=0,
        )

        assert decision_at_24h.allow_new_test is True
        assert decision_after_24h.reasons == (GateReason.OFFLINE_TOO_LONG,)
        _assert_existing_work_remains_allowed(decision_after_24h)
    finally:
        store.close()


def test_capacity_gate_has_exact_pending_session_boundary_and_retains_confirmed_raw(
    tmp_path: Path,
) -> None:
    """Catch READY_FOR_NETWORK formal handoffs being omitted from session capacity."""

    now_ns = 9_000_000_000_000
    store = _store(tmp_path)
    try:
        store.put_subject_ref("subject-1", b"opaque")
        store.record_successful_online(now_ns)
        for index in range(49):
            _commit_handoff(store, tmp_path, index=index, byte_count=1)

        decision_with_49_handoffs = store.evaluate_new_test(
            now_ns=now_ns,
            free_disk_bytes=PENDING_BYTE_LIMIT + 1,
            estimated_test_bytes=0,
        )
        confirmed_session_id, confirmed_segment_path = _commit_handoff(
            store, tmp_path, index=49, byte_count=1
        )
        uploading_handoff = store.lease_sync_handoff(now_ns=now_ns)
        assert uploading_handoff is not None
        assert uploading_handoff.session_id == confirmed_session_id
        assert store.sync_handoff_state(confirmed_session_id) == "UPLOADING"

        decision_with_50_handoffs = store.evaluate_new_test(
            now_ns=now_ns,
            free_disk_bytes=PENDING_BYTE_LIMIT + 1,
            estimated_test_bytes=0,
        )

        assert decision_with_49_handoffs.allow_new_test is True
        assert decision_with_50_handoffs.reasons == (
            GateReason.PENDING_SESSION_LIMIT,
        )
        _assert_existing_work_remains_allowed(decision_with_50_handoffs)

        uploading_snapshot = store.offline_snapshot()
        assert uploading_snapshot.pending_session_count == 50
        assert uploading_snapshot.pending_bytes == 50

        store.mark_cloud_confirmed(confirmed_session_id, confirmed_at_ns=now_ns)

        confirmed_snapshot = store.offline_snapshot()
        assert confirmed_snapshot.pending_session_count == 49
        assert confirmed_snapshot.pending_bytes == 49
        assert confirmed_segment_path.exists()
    finally:
        store.close()


def test_capacity_gate_has_exact_pending_byte_boundary(tmp_path: Path) -> None:
    """Catch READY_FOR_NETWORK formal handoffs being omitted from byte capacity."""

    now_ns = 9_000_000_000_000
    store = _store(tmp_path)
    try:
        store.put_subject_ref("subject-1", b"opaque")
        store.record_successful_online(now_ns)
        _commit_handoff(store, tmp_path, index=0, byte_count=PENDING_BYTE_LIMIT - 1)

        decision_with_2gib_minus_1 = store.evaluate_new_test(
            now_ns=now_ns,
            free_disk_bytes=PENDING_BYTE_LIMIT + 1,
            estimated_test_bytes=0,
        )
        _commit_handoff(store, tmp_path, index=1, byte_count=1)
        decision_with_2gib = store.evaluate_new_test(
            now_ns=now_ns,
            free_disk_bytes=PENDING_BYTE_LIMIT + 1,
            estimated_test_bytes=0,
        )

        assert decision_with_2gib_minus_1.allow_new_test is True
        assert decision_with_2gib.reasons == (GateReason.PENDING_BYTE_LIMIT,)
        _assert_existing_work_remains_allowed(decision_with_2gib)
    finally:
        store.close()


def test_capacity_counts_every_nonconfirmed_handoff_state(tmp_path: Path) -> None:
    """Catch a state-specific query silently dropping retry, conflict, or blocked work."""

    store = _store(tmp_path)
    try:
        store.put_subject_ref("subject-1", b"opaque")
        retry_session_id, _ = _commit_handoff(store, tmp_path, index=0, byte_count=1)
        retry_handoff = store.lease_sync_handoff(now_ns=1)
        assert retry_handoff is not None
        assert retry_handoff.session_id == retry_session_id
        store.defer_sync_handoff(
            retry_handoff.session_id,
            next_attempt_at_ns=2,
            error_code="E-SYN-001",
        )

        conflict_session_id, _ = _commit_handoff(
            store, tmp_path, index=1, byte_count=2
        )
        conflict_handoff = store.lease_sync_handoff(now_ns=1)
        assert conflict_handoff is not None
        assert conflict_handoff.session_id == conflict_session_id
        store.mark_sync_handoff_conflict(conflict_handoff.session_id)

        blocked_session_id, _ = _commit_handoff(
            store, tmp_path, index=2, byte_count=4
        )
        blocked_handoff = store.lease_sync_handoff(now_ns=1)
        assert blocked_handoff is not None
        assert blocked_handoff.session_id == blocked_session_id
        store.mark_sync_handoff_blocked(blocked_handoff.session_id, error_code="E-SYN-400")

        ready_session_id, _ = _commit_handoff(store, tmp_path, index=3, byte_count=8)
        snapshot = store.offline_snapshot()

        assert store.sync_handoff_state(ready_session_id) == "READY_FOR_NETWORK"
        assert snapshot.pending_session_count == 4
        assert snapshot.pending_bytes == 15
    finally:
        store.close()
