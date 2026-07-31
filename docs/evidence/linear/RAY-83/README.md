# RAY-83 Evidence - 数据处理管线：48×64@约12Hz、标定与显示解耦

- Issue: RAY-83 — 数据处理管线：48×64@约12Hz、标定与显示解耦
- URL: https://linear.app/ray-app/issue/RAY-83/数据处理管线4864约12hz标定与显示解耦
- Captured at: 2026-07-20T10:21:02Z
- Snapshot: In Review; milestone P1：可靠采集; priority High
- Relations: related to RAY-80

## Acceptance snapshot

- [x] Fixed-slot bounded storage buffer applies backpressure or an explicit `Full` error; it never evicts an accepted raw frame.
- [x] Raw frames remain immutable 48×64 `uint16` counts; a display projection is a separate read-only array.
- [x] Physical output units require a calibration version, fixture SHA-256, and explicit transform. Current profile remains `raw_count` only.
- [x] Algorithm/filter/bad-point/interpolation versions and immutable parameter content contribute to the processing identity.
- [x] Storage path has zero silent-drop semantics; latest-display mailbox may replace stale display-only frames and audits replacements.
- [x] Display refresh cadence is configured independently from the nominal 12 Hz input cadence.
- [x] Serializable session manifest contains data, device, protocol, calibration, algorithm, filter, bad-point, interpolation, test-protocol, and acquisition-mode versions.
- [x] Automatic synthetic benchmark covers a deliberately slow storage consumer, stalled display consumer, and parallel upload-like read/hash workload.
- [ ] Real disk, concurrent sealed-segment upload, physical 1 Mbps acquisition, and human UI-stall performance remain unverified.

## Implementation and key decisions

- `client/device/pipeline.py`
  - Adds a preallocated ring buffer with blocking backpressure, explicit timeout failure, FIFO ordering, and bounded counters.
  - Defines raw-only processing profiles, parameter identity SHA-256, separate display projections, session-version manifest serialization, and an independent display cadence.
  - Does not implement an unapproved filter, bad-point repair, interpolation algorithm, calibration curve, or physical unit conversion.
- `client/device/acquisition.py`
  - Adds `publish_count` and `replacement_count` to the single-slot latest-frame mailbox without changing storage ordering.
- `client/device/pipeline_benchmark.py`
  - Provides a short repeatable synthetic stress runner. It uses a slow in-memory consumer and a parallel read/hash workload; this is not a real disk or cloud-upload benchmark.
- `tests/device/test_pipeline.py`, `tests/device/test_pipeline_benchmark.py`
  - Cover fixed capacity, explicit full behavior, zero silent-drop metric, display replacement audit, calibration gate, raw immutability, parameter identity, version round trip, cadence separation, and stress invariants.

The DO-P4864 CheckSum coverage, length-field byte order, physical calibration, and real filter parameters remain external evidence gates. No value is guessed here.

## Verification

Detailed command output: [verification.txt](verification.txt)

Machine-readable benchmark: [benchmark.json](benchmark.json)

| Command | Result |
|---|---|
| bundled Python `-m unittest tests.device.test_pipeline tests.device.test_pipeline_benchmark` | PASS — 8 tests (0.047s) |
| bundled Python `-m unittest discover -s tests -p 'test_*.py'` | PASS — 38 owned tests (0.047s) |
| bundled Python `-m compileall -q client/device tests/device` | PASS — exit 0 |
| bundled Python `-m client.device.pipeline_benchmark --frames 120 --capacity 4 --storage-delay 0.001` | PASS — 120/120 ordered storage frames, 0 silent drops, 116 producer waits, 119 display replacements |

## Automatic / physical / manual boundary

- Automated: the unit/integration tests and benchmark use synthetic `RawFrame` objects, an in-memory fixed-slot buffer, a sleeping consumer, a stalled latest-frame reader, and a local hash thread.
- Physical not run: no DO-P4864/CH340 fixture, USB stream, real disk pressure, device timing, or cable-removal test was run.
- Upload not run: no cloud API is implemented or invoked. The parallel reader only approximates local contention from an uploader reading immutable data.
- Manual/UI not run: UI is outside this task's ownership. The cadence contract is tested, but no rendered interface or operator workflow was assessed.
- Persistence integration pending: RAY-87/RAY-89 must store the session-version manifest with encrypted segment/SQLite state.

## Failures and limits

- `elapsed_seconds` and parallel-reader iteration count are host-dependent observations, not acceptance thresholds.
- A full storage buffer never silently drops, but an explicit timeout failure still requires the acquisition coordinator to mark the session incomplete; RAY-80 covers that storage-handoff failure path.
- Algorithm version fields describe provenance contracts only; approved processing algorithms and calibration artifacts do not yet exist in this repository slice.

## Commit

Implementation/tests/benchmark/evidence commit:
`83b0357cbee8d3c339fdd19f7003785ec87477bb`.

## 2026-07-23 hardware preprocessing and standard-output update

The current MVP no longer stops at raw-only display data. The implemented hardware gate is:

```text
immutable uint8 raw frame
  → baseline/MAD bad-cell assessment
  → isolated-cell repair in a separate matrix only
  → zero correction and V1 estimated_force_n
  → VALID: encrypted raw + encrypted derived observation + SQLite index
  → INVALID: delete all temporary artifacts, no formal session
```

`client/hardware_standardization/quality.py` implements
`quality-policy/do-p4864-mvp/1`: at most two persistent bad cells, no 8-neighbour adjacency,
and four valid orthogonal neighbours required for repair. Edge cells, clusters, excess cells,
baseline instability, saturation or an unusable V1 conversion invalidate the whole capture.
`client/hardware_standardization/calibrated_array.py` preserves `raw_count` while exposing
`repaired_count`, `repaired_cell_mask`, zero-corrected values and `estimated_force_n`.
`client/spool/derived_artifact.py` persists the derived observation as a separately encrypted,
authenticated immutable artifact; it includes the baseline and repair-policy provenance but does
not duplicate raw matrices already held in encrypted raw segments.

Automated verification on 2026-07-23:

- `./scripts/local-env.sh python -m pytest tests/device tests/spool tests/hardware_standardization -q` — **98 passed**.
- `git diff --check` — passed.

Not yet verified on physical hardware: a real ≥5-second unloaded baseline, bad-point injection
against a board, saturation behavior, true sustained device timing and operator confirmation of
the re-test flow. These are required before Done.

## 2026-07-30 P1 re-verification

The RAY-83 acceptance was reread against the current observed compact profile
(3,079-byte `uint8`, 48×64 column-major, observed 20.7 Hz—not the historical
12 Hz wording in this issue title). The software boundary is covered by the
current tests: raw frames are immutable; repair produces a separate derived
matrix; valid sessions alone create encrypted raw/derived artifacts and the
minimal public `estimated-force-session/1.0` export; invalid quality results
produce neither a formal session nor a public export. The public export test
asserts that it contains no raw counts, source index, protocol, CheckSum,
quality flags, repair mask/method or estimated-force field.

```text
bash scripts/local-env.sh python -m pytest tests/hardware_standardization tests/device/test_session_runtime.py tests/spool -q
```

Result: **88 passed in 1.24s**. Configured pre-commit, mypy, `uv lock --check`
and `git diff --check` also passed. The configured mypy target remains the
serial/parser contract rather than the whole standardization package.

The connected-device capture is usable as raw parser/replay evidence only. It
has no approved ≥5-second unloaded baseline, force-calibration artifact or
physical saturation/bad-point injection; therefore it cannot be promoted to a
valid physical-pressure session or used to validate `estimated_force_n`.
RAY-83 remains `In Review`. This evidence update is committed separately from
the implementation to preserve that boundary.

## 2026-07-30 RAY-86 overlap reconciliation

RAY-86 supplies true-device evidence for the parts of this pipeline that share
the reliable-session boundary: a 5.139-second empty-board baseline (111 decoded
frames), a previously recorded 600-second valid-session commit/recovery, and a
person-assisted cable removal that made the current session `INVALID` after 970
valid decoded frames. The latter created no formal SQLite session, segment,
derived artifact, network handoff, or public algorithm export after recovery.

Those runs corroborate the existing automated coverage for immutable raw versus
derived data, short-fault audit/reconstruction, invalid-session discard and the
privacy-filtered public-export contract. The common final focused command was:

```text
bash scripts/local-env.sh python -m pytest tests/device tests/spool tests/hardware_standardization tests/startup_validation client/tests/test_ray_86_hardware_ui.py client/tests/test_ray_101_controller.py client/tests/test_ray_101_coordinator.py client/tests/test_ray_101_qt_shell.py tests/device/test_hardware_ui_manual_acceptance_script.py -q
# 218 passed in 2.88s
```

This is a cross-issue evidence reference, not a physical-force claim. No
manufacturer calibration artifact, controlled physical load, saturation
injection or hardware bad-point injection was supplied. Accordingly
`estimated_force_n` remains a versioned internal estimate only, and an exported
`estimated_force_n` is the frozen screening estimate; it is not a clinical or
metrological absolute-force claim.
RAY-83 remains `In Review` for those two force-output acceptance boundaries.
RAY-86 evidence commits: `9f94fbb`, `b5396b0`, `210809b`.

## 2026-07-30 known-weight calibration reconciliation — RAY-83 accepted for P1

The preceding conclusion was too broad: it correctly records that no
manufacturer-issued or clinical/metrological calibration artifact was supplied,
but the repository does contain—and the current device specification actually
loads—a project-owned, two-group known-weight calibration for the P1 screening
scope.

- The archived DO/DP-P4864 records contain two independent known-weight groups:
  A (original contact area) and B (smaller contact area), each using the
  4.5–8.0 kg working range.  Held-out MAE was 1.643% for A and 2.855% for B.
  The record is
  `../RAY-117/known-weight-calibration-test-record-2026-07-22.md`
  (SHA-256 `ab620597f9b81adfa7f4231a35aa05393fb7e1d1cc565b8a5b0de4e10636f96a`).
- `docs/hardware/device-specifications/do-p4864/1.0.json` selects
  `do-p4864-voltage-force/mvp-screening-v1-20260722`,
  `MVP_SCREENING_ESTIMATED_V1`, a frozen two-slope monotonic
  voltage-to-force model, in the validated 4.5–8.0 kg load range.
- `CalibratedArrayAdapter` preserves every raw count and derives
  zero-corrected/repaired values separately.  Under that profile it emits only
  `estimated_force_n` and the `ESTIMATED_FORCE_V1` provenance flag.
  `export_public_physical_session()` accepts only a hardware-valid,
  locally committed session and maps that frozen estimate to the deliberately
  minimal public `estimated_force_n` contract; it exports neither raw arrays,
  voltage, repair mask, protocol nor quality detail.

Current focused regression:

```text
bash scripts/local-env.sh python -m pytest \
  tests/hardware_standardization/test_device_specification.py \
  tests/hardware_standardization/test_quality_gate.py \
  tests/hardware_standardization/test_public_export.py \
  tests/hardware_standardization/test_calibrated_array.py \
  tests/hardware_standardization/test_force_calibration_variants.py -q
# 15 passed in 0.73s
```

**Acceptance boundary:** this closes the two RAY-83 MVP checkboxes: the private
derived force pipeline and the privacy-filtered physical-point public contract
are implemented and verified for **MVP screening**.  It does **not** claim a
high-precision absolute force measurement, a human-weight reconstruction, a
clinical result, or metrological certification.  The two contact areas,
unmeasured contact profile/temperature, limited load range and missing
repeatability/long-term-drift study remain explicit follow-up limits rather
than P1 blockers.

## 2026-07-30 product terminology and input-contract migration

Product direction now fixes **all screening calculations** on the frozen
`estimated_force_n` curve.  The public hardware-to-algorithm object is
`estimated-force-session/1.0`, whose frames expose `estimated_force_n`; no
product path reads, derives, or describes a separate “real”, “final”, or
medical-grade force value.  The existing known-weight evidence establishes the
screening curve and its version, not a medical or metrological claim.

Verification after migration:

```text
bash scripts/local-env.sh python -m pytest \
  tests/hardware_standardization tests/cloud/analysis \
  tests/cloud/reporting/test_static_balance_reporting.py -q --tb=short
# 135 passed in 1.04s

bash scripts/local-env.sh python -m ruff check <changed Python files>
# All checks passed
```

Implementation and contract-migration commit:
`c833b684de1a4b4f13ef0aa2e1c5f7a3c1625b98`.
