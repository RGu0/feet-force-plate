# RAY-119 — 动态坏点掩码、修复与设备健康门控

- Issue: [RAY-119](https://linear.app/ray-app/issue/RAY-119/动态坏点掩码修复与设备健康门控)
- Evidence captured: 2026-07-28
- State after automated verification: `In Progress`; milestone: `P1：可靠采集`; priority: `High`
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
partitions only mutable, board-specific health history. The runtime constructs a
store from the selected `device_id`, so two boards may alternate at one site
without cross-contaminating their masks. QR-code and manual-entry flows are
intentionally deferred: they will only be ways to obtain the same stable ID.
Schema `dynamic-defect-mask/2` stores `device_id`; prior `/1` snapshots are
rejected until an operator assigns their device ID explicitly, preventing an
unproven old terminal binding from being attached to the wrong board.

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

  Result: **148 passed in 1.41s**. It covers SQLite history persistence and
  redaction in addition to the existing mask/quality coverage.
- The current macOS host did not enumerate any `/dev/cu.usbserial*` device on
  2026-07-29, so true dynamic-load validation was not run and is not claimed.
- UI device selection/binding remains UI-layer acceptance. The hardware core
  offers the device-ID keyed mask and `SENSOR_DATA_UNUSABLE` failure path, but
  no customer UI is implemented in this issue.
- Raw matrices remain immutable. The mask, repair methods and health reasons
  remain hardware-private and do not cross the algorithm input boundary.

## Pending evidence boundary

RAY-119 must remain `In Review` until a connected board is exercised with a
dynamic load protocol and the UI layer verifies selected device-ID-to-physical-
device binding. These conditions are external to the completed hardware code.

## Commit

Hardware SQLite audit implementation: `167c962` — `Persist hardware dynamic mask health audit`.

## 2026-07-30 true-device dynamic-load runtime attempt

With `/dev/cu.usbserial-1140` unoccupied, four local-only pressure windows were
captured and evaluated with an explicit validation-only, unbound `device_id` in
an isolated `/private/tmp` data root. The first three windows did not meet the
dynamic policy threshold. The fourth did, and exercised frozen-mask v0 loading,
atomic v1 persistence and a raw-data-free `MASK_UPDATED` SQLite health event.
It produced 1,949 `SUSPECT` candidates but zero `REPAIRABLE` cells, so no
repair/health-block conclusion was made.

The observed compact profile's raw load semantics remain unverified; this broad
candidate set must not be interpreted as physical bad points or as a board
health result. The run proves the runtime route on true bytes, not physical
defect-detection accuracy or device-ID binding. Full evidence and boundaries:
[`2026-07-30-live-dynamic-load-attempt.md`](2026-07-30-live-dynamic-load-attempt.md),
commit `395fd3e`. RAY-119 remains `In Review` pending confirmed raw semantics/
controlled load validation and the separately required UI device binding flow.
