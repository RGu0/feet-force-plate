# RAY-119 — 动态坏点掩码、修复与设备健康门控

- Issue: [RAY-119](https://linear.app/ray-app/issue/RAY-119/动态坏点掩码修复与设备健康门控)
- Evidence captured: 2026-07-30
- State after automated verification: `In Review`; milestone: `P1：可靠采集`; priority: `High`
- Project: `足底压力健康筛查与分析平台`
- Device-ID implementation commit: `f169a36` (`Key dynamic masks by device ID`)

## Implemented algorithm

`client/hardware_standardization/dynamic_defect_mask.py` adds a versioned,
per-physical-`device_id` mask snapshot. It never stores raw frame values.

`DynamicDefectMaskStore` keeps the mutable snapshot under the application data
root, not under the source tree: `hardware/do-p4864/<sha256(device_id)>/
dynamic-defect-mask.json`. At session start the store returns a frozen snapshot
for quality/repair. Only after the session does it detect new dynamic evidence,
check for a stale concurrent snapshot, `fsync` a temporary file and atomically
replace the next version. Thus a new candidate cannot alter a running session.

The static DO-P4864 device specification remains shared by model; `device_id`
partitions only mutable, board-specific health history. The hardware core
accepts a store created from the selected `device_id`, so two boards can have
non-contaminating masks. Product UI selection/binding remains an outstanding
acceptance item. Schema `dynamic-defect-mask/2` stores `device_id`; prior `/1`
snapshots are rejected until an operator assigns their device ID explicitly,
preventing an unproven old terminal binding from being attached to the wrong
board.

1. A candidate is considered only when the observed pressure field changes by
   the configured dynamic range.
2. The candidate must have enough frames where either its vertical or horizontal
   immediate neighbours are both loaded, while the candidate's response remains
   below the configured fraction of those neighbours.
3. The candidate's own 5th–95th percentile range must also be materially lower
   than its neighbours' range. This prevents a static unloaded region from being
   called a bad point.
4. First independent session evidence creates `SUSPECT`; the next independent
   corroborating session promotes it to `REPAIRABLE`.
5. Every test freezes the mask at its start. A new observation returns the next
   mask snapshot for later review/persistence; it does not change the active
   session's physical-point layout.

`DoP4864HardwareQualityGate` accepts a frozen mask:

- isolated `REPAIRABLE` points are passed to existing derived-only neighbourhood
  repair;
- more than two repairable points, a repairable adjacent cluster, or a mask
  fraction beyond its versioned policy yields `DEVICE_DYNAMIC_DEFECT_MASK_UNUSABLE`;
- the caller maps that reason to the existing `SENSOR_DATA_UNUSABLE` UI action.

## Automated verification

```text
./scripts/local-env.sh python -m pytest tests/hardware_standardization -q
```

Targeted dynamic-mask plus quality-gate verification: `13 passed in 0.32s`.
Full hardware-standardization regression: `52 passed in 0.88s`.

The dynamic-mask fixtures cover a moving pressure field with one stuck interior
point, a static field, a normal moving field, an adjacent bad-point cluster,
quality-gate rejection, and derived-only repair through a frozen isolated mask.
They also cover mask-file creation, reload, promotion across two sessions,
atomic temporary-file cleanup, stale-snapshot rejection, same-model two-device
isolation and rejection of an old terminal-bound snapshot without explicit ID
assignment. Verification results are recorded after the current test run.
`python -m compileall` on the changed module and test, plus `git diff --check`,
also passed through the project's UV wrapper.

## Boundaries and remaining acceptance

- This is synthetic/automated evidence only; it does not prove that a specific
  real board's point is defective.
- The model is intentionally conservative: static or insufficiently stimulated
  locations are not candidates.
- 2026-07-29 adds `DeviceHealthAuditStore`: an independent hardware SQLite
  history under `hardware/device-health.sqlite3`, configured with WAL/FULL.
  It records only device ID, policy/mask version, health state and candidate/
  repairable counts. It contains no raw matrices, participant data or keys.
  Mask changes, unavailable health and clean-window recovery candidates are
  durable, queryable events; a recovery candidate never automatically clears a
  persistent defect mask.
- Current automated command:

  ```text
  ./scripts/local-env.sh python -m pytest tests/hardware_standardization/test_dynamic_defect_mask.py tests/device tests/spool tests/hardware_standardization -q
  ```

  Historical result: **148 passed in 1.41s**. The current regression is
  **151 passed in 1.36s** and adds frame-evidence counters, edge health gating
  and broad-candidate suppression.
- The host had no `/dev/cu.usbserial*` device on 2026-07-29. That observation
  is superseded by the 2026-07-30 connected-device capture/replay recorded
  below; it does not imply physical-force calibration or a manual load test.
- UI device selection/binding remains UI-layer acceptance. The hardware core
  offers the device-ID keyed mask and `SENSOR_DATA_UNUSABLE` failure path, but
  no customer UI is implemented in this issue.
- Raw matrices remain immutable. The mask, repair methods and health reasons
  remain hardware-private and do not cross the algorithm input boundary.

## Pending evidence boundary

RAY-119 must remain `In Review` until the UI layer verifies selected
device-ID-to-physical-device binding and repeated independent human sessions
show the same isolated hardware pattern. Physical-force calibration files and a
manual calibrated load are not prerequisites for this dynamic evidence path.

## Commit

Hardware SQLite audit implementation: `167c962` — `Persist hardware dynamic mask health audit`.

## 2026-07-30 true-device dynamic-load replay (superseded policy result)

With `/dev/cu.usbserial-1140` unoccupied, four local-only pressure windows were
captured and replayed with an explicit validation-only, unbound `device_id` in
an isolated `/private/tmp` data root. The first three windows did not meet the
then-current dynamic policy threshold. The fourth did, and under the earlier
policy produced v1 plus 1,949 `SUSPECT` candidates. It did not produce a
`REPAIRABLE` point, so no repair/health-block conclusion was made.

This historical broad candidate set must not be interpreted as physical bad
points or as a board-health result. It is superseded by the per-frame evidence
and flood-suppression replay below. The capture/replay validates parser and
mask mechanics on true bytes, not device-ID binding. Full evidence and
boundaries:
[`2026-07-30-live-dynamic-load-attempt.md`](2026-07-30-live-dynamic-load-attempt.md),
commit `395fd3e`.

## 2026-07-30 human-plantar per-frame evidence replay

Commit `c650311` adds raw-data-free positive-frame/support-opportunity counters
to each retained candidate, strict edge handling, schema `/3`, and suppression
of a broad candidate flood before it can pollute the next-session mask. The
same 1,240-frame real human-plantar window produced 2,138 broad candidates,
all suppressed: v0 remained v0, with zero `SUSPECT` and `REPAIRABLE` entries
and a single `SUSPECT_FLOOD_SUPPRESSED` audit event. This is not a physical
defect or defect-free-board conclusion; it proves the intended protection
against normal human-contact geometry being stored as a bad point.

Full evidence, commands and remaining boundary:
[`2026-07-30-human-plantar-frame-evidence.md`](2026-07-30-human-plantar-frame-evidence.md).
RAY-119 remains `In Review` for real UI device binding and repeated independent
session/person evidence of one isolated hardware pattern.
