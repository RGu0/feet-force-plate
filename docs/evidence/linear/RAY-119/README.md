# RAY-119 — 动态坏点掩码、修复与设备健康门控

- Issue: [RAY-119](https://linear.app/ray-app/issue/RAY-119/动态坏点掩码修复与设备健康门控)
- Evidence captured: 2026-07-28
- State after automated verification: `In Progress`; milestone: `P1：可靠采集`; priority: `High`
- Project: `足底压力健康筛查与分析平台`

## Implemented algorithm

`client/hardware_standardization/dynamic_defect_mask.py` adds a versioned,
per-device-bound mask snapshot. It never stores raw frame values.

`DynamicDefectMaskStore` keeps the mutable snapshot under the application data
root, not under the source tree: `hardware/do-p4864/<sha256(binding)>/
dynamic-defect-mask.json`. At session start the store returns a frozen snapshot
for quality/repair. Only after the session does it detect new dynamic evidence,
check for a stale concurrent snapshot, `fsync` a temporary file and atomically
replace the next version. Thus a new candidate cannot alter a running session.

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

Result after mask-file persistence: `50 passed in 0.93s`. Targeted dynamic-mask
and quality-gate tests: `11 passed in 0.31s`.

The dynamic-mask fixtures cover a moving pressure field with one stuck interior
point, a static field, a normal moving field, an adjacent bad-point cluster,
quality-gate rejection, and derived-only repair through a frozen isolated mask.
They also cover mask-file creation, reload, promotion across two sessions,
atomic temporary-file cleanup and stale-snapshot rejection.
Python compilation and `git diff --check` also passed. The current UV
environment does not include the optional `ruff` module, so no ruff result is
claimed.

## Boundaries and remaining acceptance

- This is synthetic/automated evidence only; it does not prove that a specific
  real board's point is defective.
- The model is intentionally conservative: static or insufficiently stimulated
  locations are not candidates.
- SQLite indexing/recovery history, telemetry event emission, UI binding and a
  true dynamic-load device verification remain to be completed before RAY-119
  is marked Done.
- Raw matrices remain immutable. The mask, repair methods and health reasons
  remain hardware-private and do not cross the algorithm input boundary.
