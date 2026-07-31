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

## 2026-07-30 RAY-86 overlap reconciliation

RAY-86 confirms the state-store behavior at the hardware boundary rather than
only through fixtures. Its 600-second real-device run ended `CLOSED` / `VALID`,
with one derived artifact and a fresh recovery scan that needed no recovery
action. Its person-assisted cable removal ended `INVALID` / `committed=false`;
post-run SQLite queries and filesystem inspection found zero formal sessions,
segments and artifacts.

The separate real storage-exhaustion rerun filled an isolated 8 MB volume to
100%. It reported `INVALID` with no formal session and no staging child after
cleanup. This validates the no-automatic-cleanup / fail-current-session
boundary without filling a user data volume. The two person-checked Qt failure
screens also verified the localized `E-DEV-002` retry route and `E-DAT-102`
support-only route; neither disclosed storage exceptions, paths, protocol data,
raw matrices or quality details.

The common focused regression was 218 passed (command in the RAY-86 README).
This closes the listed valid-only index, invalid discard, quota/failure mapping
and retained-session behavior at the software and available true-device
boundaries. It does not verify a production Keychain/OS adapter, a process kill
at every SQLite/fsync write, or an operator-confirmed completed-session delete
screen. RAY-89 therefore remains `In Review`. Source evidence commits:
`9f94fbb`, `b5396b0`, `210809b`.

## 2026-07-30 person-assisted single-session deletion

The deployment-owned deletion service now exposes only candidates that are
`CLOSED` / `VALID` and have no retained report. It accepts one selected session
and requires the exact per-session confirmation text `删除 <会话编号>` before
using the existing directory-move / transactional-index-delete operation. There
is no batch, scheduled, ACK-triggered, or network-triggered deletion entry
point.

The operator used a disposable temporary state root containing exactly one
valid test session, entered `删除 ray89-ui-acceptance`, and visually confirmed
the post-action result **已删除该本地会话；未影响其他会话。** Screenshot:
[`manual-session-deletion-20260730.png`](manual-session-deletion-20260730.png)
(SHA-256 `22ee4c838fdb93d7d010781d7578e59bf7af90fd42b9279d533fd42ec9a928f4`).
No production session, device stream, personal data, raw matrix or key was
opened by this acceptance launcher. Implementation, test, launcher and evidence
commit: `c5a5be8` — `Add confirmed local session deletion acceptance`.

Verification:

```text
bash scripts/local-env.sh python -m pytest client/tests/test_ray_89_session_deletion_ui.py tests/spool/test_state_store.py tests/spool/test_valid_session_commit.py -q
# 14 passed in 1.05s
bash scripts/local-env.sh python -m ruff check client/app/session_deletion.py client/app/controller.py client/app/qt_shell.py client/spool/state_store.py client/tests/test_ray_89_session_deletion_ui.py tests/spool/test_valid_session_commit.py
# All checks passed
```

The non-claimed production-hardening limits are OS secure storage and a
physical process/power failure at arbitrary filesystem/SQLite writes. The
manual-delete acceptance and the current Linear P1 checklist are complete.

## 2026-07-30 physical external state-store volume disconnect

RAY-89 additionally repeated the external-volume test in its own fresh
**Mac Flash** root. After the 5-second true-device baseline, capture began and
the operator physically removed the external volume. The external sanitized
summary reported `INVALID` / `committed=false` with a host-observed
`PermissionError`; it contains no raw frame, key or exception detail:
[`external-drive-disconnect-runtime-20260730.json`](external-drive-disconnect-runtime-20260730.json)
(SHA-256 `19cb6f63b7fba1fd63d3f4fd04ee56f91845ec278725124b78db79259a765402`).

After reattachment, the isolated root held exactly one encrypted staging
segment. Its formal SQLite count was zero for `sessions`, `segments`,
`session_artifacts`, and `sync_handoffs`. Running the existing `RecoveryScanner`
reported `interrupted_staging_discarded=1`; all four formal counts remained zero
and staging had zero children. This is direct physical data-volume-disconnect
evidence for RAY-89's valid-only index and no-automatic-handoff boundary. It is
not a host power-loss claim.
