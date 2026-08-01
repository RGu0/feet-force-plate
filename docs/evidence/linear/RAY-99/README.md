# RAY-99 Evidence — 渐进上传、断点续传与最终一致性

- Issue: `RAY-99`
- Title: 渐进上传、断点续传与最终一致性
- URL: https://linear.app/ray-app/issue/RAY-99/渐进上传断点续传与最终一致性
- Linear snapshot: `2026-07-20T09:42:20Z`
- Evidence refreshed: `2026-07-20T09:45:19Z`
- Status at implementation start: `In Progress`
- Milestone: `P3：云端闭环`
- Priority: `Urgent`
- Relations: related to `RAY-97`; no declared blockers, blocked issues, duplicates, releases, or customer needs
- Baseline: `c0e4f38113453f2c517158347b499618ce19f6f6`
- Server prerequisite: `d8466ead54cc25697185b2811c71937550f1b45b` (`RAY-97` ingestion implementation)
- RAY-99 implementation commit: `f76d042f598c0459ff57781f3b769fa379c497c2`

## Acceptance snapshot and result

- [~] SEALED segments enter a durable upload queue immediately. The shared contract admits only immutable/retryable segment states and rejects `WRITING`, `CORRUPT`, and already acknowledged segments. Atomic SQLite enqueue is client-owned and is not implemented here.
- [~] Upload is decoupled from acquisition, UI, and local reporting. The transport-neutral durable-task contract has no acquisition/UI dependency; runtime/thread performance requires client integration evidence.
- [x] Session create, segment PUT, missing query, final manifest, and status query are implemented and automatically verified by the RAY-97 server/API tests.
- [x] Tenant, terminal, session, resource ID, idempotency key, request digest, resource type, operation, attempt, lease, retry time, and timestamps are represented by the durable task and API contracts.
- [x] Same index/same digest is acknowledged idempotently; same index/different digest is a non-retryable conflict and never overwrites the accepted object.
- [~] Exponential backoff with 0–30% jitter, 1-second base, 15-minute local cap, and `Retry-After` precedence are repeatably tested. Durable task JSON round-trip proves the state is persistable, but process restart from the client SQLite repository is not integrated in this owned scope.
- [~] The resume plan automatically selects only locally present/server-absent segments. Network-monitor scheduling is client-owned and is not integration-tested here.
- [x] Local deletion is denied unless the server acknowledgement has `ACKNOWLEDGED` status and exactly the same digest.
- [x] The upload API accepts encrypted raw segment bytes plus signed metadata; client first-level features are not an authoritative ingestion input.
- [ ] Separate real client tests for 24 hours, 50 sessions, and 2 GB are not run. Policy decisions belong to RAY-100; SQLite inventory wiring belongs to the client task.
- [ ] Slow-network acquisition and local-report performance are not verified because that requires the client runtime, serial device path, and report implementation.

`[x]` means automatic evidence exists in this repository. `[~]` means only the server/shared-contract portion is complete. It does not claim client runtime or integration completion.

## Implementation files and decisions

- `shared/contracts/client_sync.py`
  - Adds a frozen, strict `DurableUploadTask` row contract matching the approved queue states and recovery fields.
  - Adds deterministic exponential backoff with injected jitter fraction so retry behavior can be repeated exactly in tests.
  - Adds `build_sync_plan`: same digest + acknowledged becomes locally acknowledged; absent remote index becomes upload; a digest/status conflict is surfaced and never auto-overwritten; remote-only facts are reported separately.
  - Adds `can_delete_local_segment`: deletion requires an exact-digest acknowledgement.
  - Adds segment-state queue eligibility; only sealed or retryable immutable data may be enqueued.
- `shared/contracts/__init__.py`
  - Exports the versioned sync contract for client consumers without coupling to a client storage implementation.
- `cloud/tests/test_client_sync_contract.py`
  - Provides repeatable tests for missing-only resume, conflicts, retention, restart serialization, task-state invariants, and retry policy.
- RAY-97 prerequisite server files exercised by the full suite include `cloud/api/app.py`, `cloud/ingestion/service.py`, and the in-memory reference repository/object store.

Key decision: a server `CONFLICT` or `QUARANTINED` receipt is never converted into a missing upload. It is returned in the conflict set for explicit intervention, preventing an automatic overwrite loop. `Retry-After` is authoritative and may exceed the local 15-minute computed cap.

## Verification commands and results

RED evidence before implementation:

```text
PYTHONPATH=. /private/tmp/feetforceplate-p3-venv/bin/python -m unittest cloud.tests.test_client_sync_contract -v
ImportError: cannot import name 'DurableUploadTask' from 'shared.contracts.client_sync'
Ran 1 test; FAILED (errors=1)
```

Targeted GREEN evidence:

```text
PYTHONPATH=. /private/tmp/feetforceplate-p3-venv/bin/python -m unittest cloud.tests.test_client_sync_contract -v
Ran 10 tests in 0.001s; OK
```

Full regression evidence:

```text
PYTHONPATH=. /private/tmp/feetforceplate-p3-venv/bin/python -m unittest discover -s cloud/tests -v
Ran 48 tests in 0.111s; OK
```

The full suite includes repeatable API tests for the server missing-set query, same-digest replay, different-digest conflict, pending-manifest gate, exact-manifest verification, and one-time Outbox publication.

Compilation evidence:

```text
PYTHONPATH=. /private/tmp/feetforceplate-p3-venv/bin/python -m compileall -q cloud shared
exit 0
```

## Automatic versus integration/manual verification boundary

Automatically verified here:

- pure resume-plan selection is deterministic and uploads only server-absent local indexes;
- digest/status conflicts remain conflicts and are not silently retried as missing;
- exact digest acknowledgement is required before local deletion;
- durable queue fields survive JSON serialization/deserialization;
- queue-state invariants and the approved retry formula;
- existing server endpoints, object immutability, missing query, manifest gate, and outbox behavior using in-memory adapters.

Not verified here:

- actual client SQLite schema, transactionally atomic `SEALED + upload_task` creation, leases, restart scan, or network monitor;
- automatic background upload after a real connection recovers;
- serial acquisition and basic-report latency under slow or lossy networks;
- real 24-hour, 50-session, and 2-GB inventory thresholds;
- deployed PostgreSQL/S3/TLS behavior already listed in RAY-97 evidence.

These missing items require client-owned code and/or an integration environment. Therefore RAY-99 must not be marked `Done`; after this commit it is eligible only for `In Review`.

## Failures and limitations

- The initial Linear status update timed out, but the retry succeeded; a subsequent `get_issue` confirmed `In Progress` and the startup comment was present.
- Automated tests use deterministic in-memory server adapters. They do not prove durability across an actual client process crash or cloud outage.
- No secrets, personal data, raw customer frames, or activation credentials are stored in this evidence directory.

## 2026-08-01 seed client refresh

- `PROVEN_LOCAL`: background access continuity refreshes credentials once across
  concurrent consumers and keeps upload/heartbeat active while the UI is locked.
- `PROVEN_LOCAL`: License suspended/expired/revoked states block only new tests;
  existing upload and report access continue.
- `PROVEN_LOCAL`: 24-hour, 50-session and 2-GiB local gates are wired to the
  current signed `license/2` client policy.
- `PROVEN_LOCAL`: synthetic ten-tenant upload, exact manifest and cross-tenant
  denial are captured in `RAY-116/seed-access-summary.json`.
- `PENDING_POSTGRES` / `PENDING_ALIYUN`: real process restart, live role DSNs,
  lossy public network and server restart durability remain open.
