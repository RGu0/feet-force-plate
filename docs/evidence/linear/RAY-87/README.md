# RAY-87 Evidence - 本地会话、加密不可变分段与崩溃恢复

- URL: https://linear.app/ray-app/issue/RAY-87/本地会话加密不可变分段与崩溃恢复
- Captured at: 2026-07-21T19:00:00-07:00
- Snapshot: In Progress; P1：可靠采集; High

## Acceptance snapshot

- [x] SQLite WAL states, `synchronous=FULL`, 5,000 ms busy timeout, and 5-10-second/size-based segmentation
- [x] zlib compression, AES-256-GCM, random 96-bit nonce and ciphertext SHA-256 digest
- [x] temp -> complete -> flush/fsync -> atomic rename -> verified `SEALED` registration transaction
- [x] only verified `SEALED` segments receive a `PENDING` upload task; versioned session manifest binds indexes, digests, versions and frame counts
- [x] recovery of complete temp, orphan sealed and interrupted-session states; tampered temp/sealed files are quarantined, and registered corrupt files transition to `CORRUPT` with upload task `QUARANTINED`
- [x] cleanup selection remains limited to acknowledged segments past their retention deadline (implemented in the shared local-state boundary; RAY-89 remains separately tracked)
- [ ] Physical power loss at every filesystem/database write instruction, actual disk-full behavior and OS secure-storage adapter behavior

## Implementation and decisions

Implemented files:

- `client/spool/segments.py`: versioned immutable `.ffps` container, authenticated
  AES-256-GCM encryption, per-file ciphertext digest, file/directory fsync and
  atomic close; preserves both current observed `48×64 uint8` frames and legacy
  synthetic `uint16` fixtures without dtype promotion.
- `client/spool/recovery.py`: reconciles complete `.tmp` files, orphan sealed files,
  interrupted acquisition states and malformed/tampered files without accepting a
  corrupt segment into the queue.
- `client/spool/state_store.py`: SQLite WAL persistence, sensitive metadata envelope,
  atomic `SEALED` plus `PENDING` registration and explicit corruption quarantine.

The content key is supplied only through `KeyProvider`; the repository and evidence
contain no key material. The filesystem and SQLite state are intentionally checked
as separate sources of truth during recovery.

## Verification

Automated verification:

- `uv run --extra dev pytest tests/spool -q` — 15 passed.
- `uv run --extra dev pytest tests/device tests/spool -q` — 55 passed.
- `uv run --extra dev python -m py_compile client/spool/state_store.py client/spool/segments.py client/spool/recovery.py` — passed.
- `git diff --check -- client/spool tests/spool` — passed before commit.

The automated suite covers: 5-second sealing, `uint8` current-profile round trip,
random nonce separation, digest/AES-GCM tamper detection, manifest binding, complete
temporary-file promotion, post-rename/pre-DB recovery, corruption quarantine,
interrupted session/upload recovery, SQLite durability configuration, quota gates and
acknowledged-only cleanup eligibility.

## Boundary, failures, and limits

This is not a real power-cut, disk-full or OS secure-storage validation. It also does
not prove that the actual DO-P4864 device provides calibrated or semantically
confirmed values. RAY-87 must remain In Review until those external acceptance cases
are performed.

## Commit

Implementation commit: `56f995d` — `Implement encrypted session spool recovery`.

## 2026-07-22 scope revision: valid-session-only persistence

The product decision now requires that hardware persist only a complete, valid
session. The previous per-segment `SEALED`/upload queue behavior remains legacy
recovery coverage; the current MVP path is:

```text
encrypted temporary segments
  → whole-session quality/preprocessing decision
  → atomically promote valid directory
  → atomically register CLOSED/VALID SQLite session and READY_FOR_NETWORK handoff
```

Invalid, interrupted, or recovery-failed captures are not formal sessions: their
temporary raw/derived artifacts are deleted and no `Session`/`Segment` database
record is created. A cloud confirmation can only change the handoff state; it
does not delete any valid local data.

Current implementation files:

- `client/spool/session_commit.py`: staging, invalid discard, valid promotion and
  startup removal of interrupted staging directories.
- `client/spool/state_store.py`: migration 3, atomic valid-session registration
  and the `sync_handoffs` state boundary.
- `tests/spool/test_valid_session_commit.py`: valid promotion, invalid discard and
  interrupted-staging recovery regression tests.

Verification after the scope revision:

- `./scripts/local-env.sh python -m pytest tests/spool -q` — 22 passed.
- `git diff --check` — passed before commit.

Remaining external/manual boundary: actual power loss, full-disk behavior and a
real-device run are still required before RAY-87 can be marked Done.

## 2026-07-23 derived-valid-session update

Schema migration 4 adds `session_artifacts`: SQLite remains a WAL/FULL index and records the
encrypted derived-observation artifact alongside raw segment references. The valid-session commit
atomically promotes the directory, records raw segments, records the derived artifact and creates
the `READY_FOR_NETWORK` handoff. A cloud confirmation still only changes handoff state.

`client/spool/derived_artifact.py` uses a versioned AES-256-GCM container with random 96-bit
nonce and ciphertext SHA-256. The payload contains only repaired/derived hardware observations
and provenance; original high-rate raw matrices remain in their existing encrypted segments.

Automated verification on 2026-07-23:

- `./scripts/local-env.sh python -m pytest tests/device tests/spool tests/hardware_standardization -q` — **98 passed**.
- `git diff --check` — passed.

## 2026-07-23 promotion-to-SQLite crash-window update

`client/spool/session_commit.py` now writes an fsync'ed, versioned registration marker before
the valid staging directory is atomically promoted. `RecoveryScanner` consumes that marker on
startup: a crash after the directory rename but before the SQLite transaction is completed is
recovered exactly once, then the marker is deleted. An ordinary SQLite exception is rolled back
to the discardable staging directory; an uncompleted staging directory remains non-session data.

Automated fault-injection verification:

- `./scripts/local-env.sh python -m pytest tests/spool/test_recovery.py tests/spool/test_valid_session_commit.py tests/device/test_session_runtime.py -q` — **17 passed**.
- Injected `SystemExit` after directory promotion confirms next-startup registration produces
  one `CLOSED` / `VALID` session and removes `registration.json`.

This is process-level simulation, not a physical power-cut or full-disk result; those RAY-87
external checks remain required.

## 2026-07-30 P1 re-verification

```text
bash scripts/local-env.sh python -m pytest tests/spool tests/device/test_session_runtime.py -q
```

Result: **32 passed in 0.42s**; `ruff check client/spool tests/spool` and
`git diff --check` passed. The suite covers encrypted temporary staging,
AES-256-GCM artifact integrity, valid-only atomic promotion and SQLite/hand-off
registration, invalid discard, post-promotion registration recovery, interrupted
staging cleanup, and retained data after cloud confirmation until an explicit
manual delete.

The connected-device capture remains local parser evidence only. Without the
approved baseline and force-conversion prerequisites, it was not promoted to a
formal session and was not used to create encrypted P1 session artifacts.
Physical power removal across filesystem/SQLite instructions, a real full-disk
run and the production OS secure-storage adapter are still not validated. RAY-87
therefore remains `In Review`; this evidence refresh has no implementation claim.

## 2026-07-30 RAY-86 overlap reconciliation

RAY-86 supplies the real-device acceptance missing from the earlier
software-only records. A 600-second production-composition run completed a
`VALID` session, atomically committed its encrypted local artifacts and SQLite
records, created one derived artifact, and produced a fresh restart scan with no
temporary, quarantine, orphan, requeue or interrupted-staging action. Candidate
checksum remained observe-only; no raw matrix or key was copied into evidence.

Two failure records corroborate the valid-only persistence boundary:

- Person-assisted cable removal produced `INVALID` / `committed=false` after
  970 valid decoded frames. Re-enumeration and SQLite/filesystem checks found
  zero formal sessions, segments and artifacts.
- A real DO-P4864 capture on an isolated 8 MB HFS+ volume filled to 100% ended
  `INVALID` / `committed=false`; after the run the volume had no staging files
  and SQLite had zero sessions, segments and derived artifacts. See
  [`../RAY-86/storage-exhaustion-runtime-20260728.md`](../RAY-86/storage-exhaustion-runtime-20260728.md).

The shared final regression was 218 passed; its exact wrapper command is
recorded in `docs/evidence/linear/RAY-86/README.md`. This validates the listed
valid-session and invalid-cleanup contracts, including `READY_FOR_NETWORK` and
retention after confirmation through automated coverage. It does **not** prove
a physical power cut at every fsync/SQLite instruction or a production OS
secure-storage adapter, so RAY-87 remains `In Review`. Source evidence commits:
`9f94fbb`, `b5396b0`, `210809b`.
