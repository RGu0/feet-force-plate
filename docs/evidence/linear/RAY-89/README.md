# RAY-89 Evidence - 本地状态库、离线配额与确认后清理

- Issue: RAY-89 — 本地状态库、离线配额与确认后清理
- URL: https://linear.app/ray-app/issue/RAY-89/本地状态库离线配额与确认后清理
- Captured at: 2026-07-20T10:29:44Z
- Snapshot: In Review; milestone P1：可靠采集; priority High
- Relations: related to RAY-83 and RAY-87

## Acceptance snapshot

- [x] SQLite schema includes minimized SubjectRef, ConsentRecord, Session, Segment, UploadTask, ReportVersion, and TerminalState records.
- [x] WAL mode, foreign keys, schema version 1, and forward-version refusal are implemented.
- [x] Subject/consent payloads use AES-256-GCM; the database stores nonce+ciphertext, while keys come only from a `KeyProvider` boundary.
- [ ] A production macOS Keychain/OS secure-storage adapter and key rotation/recovery ceremony are not implemented in this issue slice.
- [x] Startup recovery maps interrupted `ACQUIRING` sessions to `CLOSED/INCOMPLETE` and `UPLOADING` tasks back to `PENDING` atomically.
- [x] One SQLite statement returns last successful online time, distinct pending sessions, and pending bytes consistently.
- [x] 24-hour, 50-session, 2-GiB, and conservative free-disk gates prevent only new tests; current finalization, existing report view, and upload remain allowed.
- [x] Cleanup candidates require `ACKNOWLEDGED`, acknowledgement time, and expired retention; record deletion rechecks the invariant.
- [ ] Filesystem deletion ordering and crash recovery are integrated in RAY-87, not guessed in the state-only issue.

## Implementation and key decisions

- `client/spool/state_store.py`
  - Adds schema version 1 under SQLite WAL with explicit foreign keys and indexes.
  - Stores only opaque subject UUIDs plus encrypted reference/consent blobs. It does not add names, phone numbers, identity documents, or other unnecessary plaintext fields.
  - Uses AES-GCM associated data bound to record type and ID. The key-provider interface is deliberately separate from SQLite.
  - Provides recovery, offline snapshot, new-test gate, cleanup-candidate, and cleanup-finalization operations.
- `tests/spool/test_state_store.py`
  - Verifies schema/WAL, ciphertext-at-rest boundary, key absence from DB, interrupted-state recovery, all gate thresholds/permissions, and acknowledgement+retention cleanup.

## Verification

Detailed output: [verification.txt](verification.txt)

| Command | Result |
|---|---|
| bundled Python `-m unittest tests.spool.test_state_store` | PASS — 5 tests (0.021s) |
| bundled Python `-m unittest discover -s tests -p 'test_*.py'` | PASS — 43 owned tests (0.077s) |
| bundled Python `-m compileall -q client/spool tests/spool client/device tests/device` | PASS — exit 0 |

## Automatic / physical / manual boundary

- Automated: all checks use temporary SQLite databases and an injected ephemeral test key. No secret, personal data, or customer data is saved in evidence.
- OS integration not run: macOS Keychain access, entitlement behavior, locked-key handling, rotation, restore, and multi-process access remain unverified.
- Crash/disk not run: tests execute logical restart recovery but do not kill a process at arbitrary fsync/SQLite points or fill a real disk.
- Cross-module not run: report viewing, current-session UI, real uploader, and encrypted segment file deletion are outside this issue's owned implementation.

## Failures and limits

- `KeyProvider` is a required production integration boundary, not a claim that a raw key may be stored in configuration or SQLite.
- `finalize_segment_cleanup` removes only the DB record after the caller has removed the acknowledged file; RAY-87 must enforce file-delete-before-record-finalize and recover either crash window.
- The schema provides the local ReportVersion reference model but does not implement report generation or cloud APIs.
- Gate thresholds are inclusive (`>= 24h`, `>= 50`, `>= 2 GiB`) and disk preflight does not attempt opportunistic cleanup.

## Commit

Implementation/tests/evidence commit:
`db56b9e7132fbe8fbd9c6e7982260ea7869bde30`.
