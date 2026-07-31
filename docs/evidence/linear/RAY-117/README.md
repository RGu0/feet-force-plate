# RAY-117 — 硬件标准化层：原始阵列到 MVP 标准会话

- Issue: [RAY-117](https://linear.app/ray-app/issue/RAY-117/硬件标准化层原始阵列到-mvp-标准会话)
- Evidence refreshed: 2026-07-28
- State after automated verification: `In Review`; milestone: `P0：硬件基线`; priority: `Urgent`
- Project: `足底压力健康筛查与分析平台`

## Acceptance snapshot

- [x] Adapter emits a traceable derived output for 1–2 isolated, repairable
  cells without mutating the immutable raw frame.
- [x] Single-frame horizontal/vertical line detection is conservative and
  produces a separately masked, directionally interpolated processing matrix.
- [x] Bad-cell clusters, edge cells, excessive repair coverage, multiple lines,
  baseline anomalies, saturation and conversion failures invalidate the session.
- [x] Automated fixtures cover column-major mapping, normal frames, isolated
  cells, adjacent/edge cells, persistent line detection and raw immutability.
- [x] A dedicated public exporter accepts only a hardware-accepted, locally
  committed session and emits exactly `estimated-force-session/1.0`:
  board points, monotonic time and `estimated_force_n`. It rejects invalid
  or uncommitted sessions and excludes all raw, protocol, repair and quality fields.
- [x] MVP screening uses the frozen V1 force conversion; it is not presented as
  a high-precision absolute-force or clinical measurement claim.

## Public algorithm handoff

- `client/hardware_standardization/public_export.py` is the only public export
  boundary. It receives `HardwareQualityEvaluation`, requires `VALID` plus a
  completed local commit, exposes the frozen V1 force vector as `estimated_force_n`,
  and produces the minimal JSON-compatible `estimated-force-session/1.0`.
- Point identifiers are generic `point-0001`… identifiers. Their physical
  locations and each frame's force-vector ordering are stable, while all
  DO-P4864 row/column/source-index details remain internal.
- The export object has no device model, array shape/order, raw counts, voltage,
  checksum, quality state, defect mask, repair method or calibration metadata.
- This completes the hardware-layer handoff contract for MVP screening; broader
  repeatability, drift and cross-device characterization are later validation
  work and do not block this issue.

## Implementation and reuse decision

- `client/hardware_standardization/defect_repair.py` is layout-neutral: it takes
  finite non-negative 2-D matrices and emits new immutable matrices, masks and
  per-cell methods. It has no serial, UI, COP, scoring or report dependency.
- Isolated declared cells use a local 3×3/5×5 spatial median. A single frame
  can repair one high-confidence bad row/column by paired directional
  interpolation across the defect; a 5-wide window takes the median of multiple
  pairwise interpolation estimates. Cross-frame repetition is audit confidence,
  not a repair prerequisite. This retains a pressure gradient and resists one
  noisy neighbour.
- `DoP4864HardwareQualityGate` applies that repair *before* zero correction and
  standardization. Raw frames remain unchanged; `repaired_count`,
  `repaired_cell_mask`, processing metadata and the existing physical session
  provide the common derived representation for local/cloud algorithms and
  stored recovery artifacts.
- UI display refinement remains a later, display-only consumer. The current
  real-time RawFrame-to-UI composition has not been changed here; it must
  consume this standardized derived representation rather than repeat repair.

## Verification

Command (offline, external UV environment):

```text
UV_OFFLINE=1 UV_CACHE_DIR=/private/tmp/feetforceplate-uv-cache \
FEETFORCEPLATE_VENV=/private/tmp/feetforceplate-subtask-b-venv \
./scripts/local-env.sh python -m pytest tests/hardware_standardization \
  tests/device/test_session_runtime.py tests/spool/test_valid_session_commit.py \
  client/tests/test_ray_91_reference_protocol_fixture.py -q \
  --junitxml=docs/evidence/linear/RAY-117/pytest-sensor-defect-repair-20260723.xml
```

Historical result: `62 passed in 1.34s`. The JUnit output is retained as
`pytest-sensor-defect-repair-20260723.xml`; the relevant fixture observation is
retained in `sensor-defect-repair-reference-20260723.json`.

Current public-export verification command:

```text
./scripts/local-env.sh python -m pytest tests/hardware_standardization -q
```

Result on 2026-07-28: `44 passed in 0.92s`; targeted public-export test:
`2 passed in 0.20s`; Python compilation and `git diff --check` passed. The
current environment does not include the optional `ruff` module, so no ruff
result is claimed. The associated commit SHA is recorded in the Linear
completion comment after the command succeeds.

## Boundaries and limits

- The repair is derived data only: no source matrix is overwritten and it is
  not a calibration, physical-force, clinical or diagnostic assertion.
- Detection is deliberately limited to one interior row or column per frame,
  with opposite-side support and coverage gates. A different hardware profile
  must select and version its own policy; it is not safe to assume this fixture
  proves every sensor defect.
- The replay fixture is de-identified and contains no raw customer identity or
  serial capture. Broader real-device repeatability, cross-device confirmation,
  drift and runtime UI binding remain separate follow-up validation work.
- Related upstream protocol evidence is still tracked by `RAY-78`.

## Commit

Initial implementation commit: `09542f4` (`Add generic sensor defect repair`).
Single-frame follow-up commit: `b0ead9f` (`Repair sensor defects within each
frame`).

## Evidence

- `issue-snapshot.json`: Linear state captured when work began.
- `temporal-denoising-known-load-experiment-2026-07-22.md`: held-out comparison
  of stable-frame median and temporal mean denoising.
- `curve-and-processing-benchmark-2026-07-22.md`: leave-one-load-out comparison
  of monotonic response curves, free `V0` fitting and activity/background
  processing variants.
- `unified-fit-method-and-result-2026-07-22.md`: the selected one-curve A+B
  calibration candidate, its parameter values, and independent human replay.
- `unified-fit-validation-2026-07-22.png`: the corresponding mass, pressure and
  point-response visualization for A, B and human replay conditions.
- `known-weight-calibration-test-record-2026-07-22.md`: DP-P4864 conditions,
  processing method, limits and future calibration procedure for the two
  known-weight capture groups.
- `known-weight-calibration-sha256-2026-07-22.txt`: integrity manifest for the
  14 selected raw frames. The verified external archive is under
  `Device/DP-P4864/Calibration/2026-07-22-known-weight-calibration/`.
- `sensor-defect-repair-reference-20260723.json`: de-identified replay fixture
  result for the generic pre-interpolation repair; no raw matrices are copied.
- `pytest-sensor-defect-repair-20260723.xml`: 61-test automated regression log.

## Result boundary

The selected MVP device profile is
`do-p4864-voltage-force/mvp-screening-v1-20260722`, using
`voltage-to-force/two-slope-monotonic/1`. It supports the current initial
screening product flow, not high-precision absolute-force, clinical or
metrological claims.
