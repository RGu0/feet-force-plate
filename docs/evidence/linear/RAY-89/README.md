# RAY-89 Evidence - 本地状态库、离线配额与确认后清理

- Issue: RAY-89 — 本地状态库、离线配额与确认后清理
- URL: https://linear.app/ray-app/issue/RAY-89/本地状态库离线配额与确认后清理
- Captured at: 2026-07-21T19:10:00-07:00
- Snapshot: In Review; milestone P1：可靠采集; priority High
- Relations: related to RAY-83 and RAY-87

## Acceptance snapshot

- [x] SQLite schema includes minimized SubjectRef, ConsentRecord, Session, Segment, UploadTask, ReportVersion, and TerminalState records.
- [x] WAL mode, foreign keys, `synchronous=FULL`, 5,000 ms busy timeout, schema version 1, and forward-version refusal are implemented.
- [x] Subject/consent payloads use AES-256-GCM; the database stores nonce+ciphertext, while keys come only from a `KeyProvider` boundary.
- [ ] A production macOS Keychain/OS secure-storage adapter and key rotation/recovery ceremony are not implemented in this issue slice.
- [x] Startup recovery maps interrupted `ACQUIRING` sessions to `CLOSED/INCOMPLETE` and `UPLOADING` tasks back to `PENDING` atomically.
- [x] One SQLite statement returns last successful online time, distinct pending sessions, and pending bytes consistently.
- [x] 24-hour, 50-session, 2-GiB, and conservative free-disk gates prevent only new tests; current finalization, existing report view, and upload remain allowed.
- [x] Cleanup candidates require `ACKNOWLEDGED`, acknowledgement time, and expired retention; cleanup deletes the file, fsyncs its directory, then rechecks and removes the SQLite record.
- [x] A corrupted/quarantined segment remains in pending session/byte accounting until an explicit repair or eligible cleanup path resolves it.

## Implementation and key decisions

- `client/spool/state_store.py`
  - Adds schema version 1 under SQLite WAL with explicit foreign keys and indexes.
  - Stores only opaque subject UUIDs plus encrypted reference/consent blobs. It does not add names, phone numbers, identity documents, or other unnecessary plaintext fields.
  - Uses AES-GCM associated data bound to record type and ID. The key-provider interface is deliberately separate from SQLite.
  - Provides recovery, offline snapshot, new-test gate, foreign-key-safe sensitive-record updates, cleanup-candidate, and cleanup-finalization operations.
- `client/spool/recovery.py`
  - Executes acknowledged cleanup in the safe order: check eligible record, remove the
    in-root segment file, fsync the directory, then finalize the SQLite record. A
    deletion error leaves both the file and record in place; a restart after deletion
    but before DB finalization can safely finalize the still-eligible record.
- `tests/spool/test_state_store.py`
  - Verifies schema/WAL/FULL durability, ciphertext-at-rest boundary, key absence
    from DB, foreign-key-safe encrypted-reference updates, interrupted-state recovery,
    all gate thresholds/permissions, corrupt-byte accounting, and acknowledgement+
    retention cleanup.
- `tests/spool/test_recovery.py`
  - Verifies filesystem-before-DB cleanup plus an injected deletion failure that must
    leave the acknowledged state record intact.

## Verification

Detailed output: [verification.txt](verification.txt)

| Command | Result |
|---|---|
| `uv run --extra dev pytest tests/spool -q` | PASS — 19 tests |
| `uv run --extra dev pytest tests/device tests/spool -q` | PASS — 59 tests |
| `uv run --extra dev python -m py_compile client/spool/state_store.py client/spool/segments.py client/spool/recovery.py` | PASS |

## Automatic / physical / manual boundary

- Automated: all checks use temporary SQLite databases and an injected ephemeral test key. No secret, personal data, or customer data is saved in evidence.
- OS integration not run: macOS Keychain access, entitlement behavior, locked-key handling, rotation, restore, and multi-process access remain unverified.
- Crash/disk not run: tests execute logical restart recovery and injected unlink failure but do not kill a process at arbitrary fsync/SQLite points or fill a real disk.
- Cross-module not run: report viewing, current-session UI, real uploader, and encrypted segment file deletion are outside this issue's owned implementation.

## Failures and limits

- `KeyProvider` is a required production integration boundary, not a claim that a raw key may be stored in configuration or SQLite.
- `cleanup_acknowledged_segments` only accepts an in-root, already acknowledged and expired candidate. It is still not a real disk-full or process-kill test.
- The schema provides the local ReportVersion reference model but does not implement report generation or cloud APIs.
- Gate thresholds are inclusive (`>= 24h`, `>= 50`, `>= 2 GiB`) and disk preflight does not attempt opportunistic cleanup.

## Commit

Implementation commit: `dc6042d` — `Harden offline quota and acknowledged cleanup`.

## 2026-07-23 retention-policy revision

The old ACK/retention cleanup behavior is superseded. `cleanup_acknowledged_segments` is now an
intentional compatibility no-op, and `StateStore.cleanup_candidates()` returns no candidates:
cloud confirmation never deletes a file or index automatically.

`StateStore.valid_local_storage_snapshot()` reports the valid-session count, raw-plus-derived
stored bytes, pending network handoffs and most recent cloud confirmation. `delete_completed_valid_session()`
is an operator-only, single-session function: it atomically moves `sessions/<id>` to a hidden
deletion directory, removes the completed valid session's SQLite references in one transaction,
then removes the hidden directory. If the database operation fails the directory is moved back.
Sessions with retained report references are refused rather than partially deleted.

Automated verification on 2026-07-23:

- `./scripts/local-env.sh python -m pytest tests/device tests/spool tests/hardware_standardization -q` — **104 passed**.
- `git diff --check` — passed.

Physical crash-at-fsync, actual disk-full behavior, OS secure-storage adapter and operator UI
confirmation of a delete action remain unverified; the issue must remain In Review.

## 2026-07-30 P1 re-verification

```text
bash scripts/local-env.sh python -m pytest tests/spool/test_state_store.py tests/spool/test_valid_session_commit.py tests/device/test_session_ui.py tests/device/test_session_runtime.py -q
```

Result: **23 passed in 0.34s**; `ruff check client/spool tests/spool
tests/device/test_session_ui.py` and `git diff --check` passed. The checks cover
valid-only indexing and `READY_FOR_NETWORK`, invalid-session discard, offline
count/byte/pending-handoff/last-confirmation snapshot, safe storage and
finalization failure mapping, confirmation retention, and single completed-valid
session deletion. No test invokes a cloud API or an automatic cleanup action.

The remaining acceptance boundary is unchanged: production OS secure storage,
physical crash/disk-full behavior, and a human UI confirmation of the delete
flow. RAY-89 remains `In Review`; this is a verification-evidence refresh only.
