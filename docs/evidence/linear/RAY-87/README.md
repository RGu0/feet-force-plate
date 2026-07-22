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
