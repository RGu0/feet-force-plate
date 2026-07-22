# RAY-117 Hardware Physical Array Standardization Plan

**Status:** scope and implementation plan only; RAY-117 remains `Backlog` until implementation is explicitly started.

**Goal:** provide a versioned, device-independent physical-layer input contract. It maps each immutable decoded sensor array to board-plane point coordinates plus raw, zero-corrected, and relative-load values. It does not calculate subject ML/AP, COP, gait metrics, risk, reports, or UI state.

**Architecture:** `client.hardware_standardization` receives already-decoded immutable frames through an adapter port and outputs `physical-array-session/1.0`. The generic layer supports arbitrary regular or irregular layouts and never hardcodes DO-P4864 dimensions. The DO-P4864 adapter owns only its known column-major source mapping and user-confirmed board-grid declaration. A separate baseline-input port supplies a qualifying unloaded window; no serial parsing or startup workflow is duplicated in this issue.

**Technology:** Python through `./scripts/local-env.sh`, frozen dataclasses, `Protocol`, NumPy, JSON Schema Draft 2020-12, pytest.

## Confirmed scope and boundaries

- Scope is Linear issue `RAY-117` only. Do not modify UI, cloud/API, upload/encryption, identity, risk/report logic, local analysis, or serial byte decoding.
- Before functional work, re-read the Linear project, RAY-117, and RAY-78; move only RAY-117 to `In Progress`, add the prescribed start comment, and re-read it. Evidence is kept in `docs/evidence/linear/RAY-117/README.md`.
- Preserve source arrays byte-for-byte and read-only. The standardizer creates new output arrays only.
- Every output frame uses actual strictly increasing host-monotonic timestamps; never synthesize time from an assumed rate or fill gaps.
- The contract is board-plane only: no `ml_mm`, `ap_mm`, body orientation, COP, displacement, velocity, stage, risk, or report fields.
- A 5-second unloaded window establishes a *zero reference and noise characterization*. It does not establish Newtons, Pascals, an electrically effective area, gain/nonlinearity, temperature compensation, or a body coordinate transform. Until a known-load calibration profile is separately verified, `normal_force_n` is `null` and the output is explicitly degraded.

## DO-P4864 board geometry (user-confirmed)

```text
coordinate frame: BOARD_TOP_LEFT_X_RIGHT_Y_DOWN
origin:           row=0, column=0 sensor-point centre = (0, 0) mm
coordinate axes:  x is rightward; y is downward
grid:             48 rows x 64 columns
point pitch:      7.99 mm rightward and 7.99 mm downward
point coordinate: x_mm = column * 7.99; y_mm = row * 7.99
source index:     column * 48 + row (observed column-major compact mapping)
last centre:      row=47, column=63 = (503.37, 375.53) mm
observed region:  approximately 381.3 x 509.3 mm (user measurement)
nominal point:    6 x 6 mm (supplier image); 36 mm2 is nominal metadata only
```

The supplier image lists a 7 x 7 mm spacing. It is retained as source metadata only and is superseded for coordinates by the user-confirmed 7.99 mm pitch. The approximate region dimensions are corroborating physical dimensions, not an alternative coordinate formula.

Known protocol facts remain limited to the already-decoded RAY-78 output: 3,079-byte observed frames, 3,072 `uint8` counts, 48 x 64 column-major reshape, candidate checksum audit-only, and roughly 20.7 Hz observed host cadence. The physical layer does not parse or reject frames based on the candidate checksum.

## Calibration / zero-reference semantics

### Required input port

RAY-117 defines an immutable `UnloadedBaselineWindow` input with:

- a unique baseline/window ID and schema version;
- source device and layout identity/digest;
- complete 5-second no-load host-monotonic interval;
- immutable decoded raw frames and their timestamps;
- the associated `DeviceValidationRun` summary and a requirement that its outcome is `PASS`;
- provenance digest, validation-rule version, and threshold version.

The existing `DeviceValidationRun` currently records only a summary/statistics; it does **not** retain raw frames. Therefore RAY-117 must accept this baseline window through a port and use fixtures for its unit tests. A production provider that safely exposes the 5-second immutable window is an integration dependency of RAY-113; this issue must not modify RAY-113's capture/workflow or fabricate the missing window.

### Per-cell computation

For each active point in a layout-matched, PASS baseline window:

```text
zero_offset_count = median(unloaded raw counts for that point)
noise_mad_count   = median(abs(unloaded raw count - zero_offset_count))
zero_corrected_count = current_raw_count - zero_offset_count
relative_load_count  = max(zero_corrected_count, 0)
```

`raw_count`, `zero_corrected_count`, and `relative_load_count` are separate fields. No value is overwritten or silently clamped. `relative_load_count` is the spatially positioned, baseline-corrected *relative signal*, not a pressure unit. A validated known-load transfer function may later additionally produce `normal_force_n`; that path must be versioned, have uncertainty, and pass explicit force-validation gates.

### Stable quality flags

`BASELINE_MISSING`, `BASELINE_VALIDATION_NOT_PASSED`, `BASELINE_WINDOW_INCOMPLETE`, `BASELINE_LAYOUT_MISMATCH`, `BASELINE_NOISE_HIGH`, `ZERO_OFFSET_APPLIED`, `FORCE_UNCALIBRATED`, `ACTIVE_AREA_UNVALIDATED`, `MISSING_CELL_SAMPLE`, `BAD_CELL_EXCLUDED`, `CELL_SATURATED`, `SOURCE_INDEX_GAP`, `LONG_FRAME_INTERVAL`, `TIMESTAMP_NOT_STRICTLY_INCREASING`, and `SOURCE_INTEGRITY_UNVERIFIED`.

Threshold ownership remains with the RAY-113 validation profile for initial release. RAY-117 records the threshold/profile version rather than inventing new device pass/fail limits.

## Planned file changes

**Create**

- `client/hardware_standardization/__init__.py` — public port and model exports.
- `client/hardware_standardization/models.py` — immutable sessions, point cells, frame values, baseline reference, quality, uncertainty, provenance, outcomes.
- `client/hardware_standardization/ports.py` — array-adapter and baseline-window provider protocols.
- `client/hardware_standardization/geometry.py` — generic regular/irregular layout validation and board coordinates.
- `client/hardware_standardization/baseline.py` — baseline-reference construction and zero correction only.
- `client/hardware_standardization/calibrated_array.py` — generic arbitrary-layout standardizer and optional validated force-profile gate.
- `client/hardware_standardization/do_p4864.py` — decoded DO-P4864 adapter with the confirmed grid/mapping, no byte parsing.
- `client/hardware_standardization/serialization.py` — deterministic JSON conversion.
- `docs/algorithm/schemas/physical-array-session-1.0.schema.json` — normative schema.
- `tests/hardware_standardization/test_models.py`, `test_geometry.py`, `test_baseline.py`, `test_calibrated_array.py`, `test_do_p4864_adapter.py`, `test_serialization.py`, `test_dependency_boundary.py`.
- `tests/fixtures/hardware_standardization/{baseline-window,regular-grid,irregular-array,quality-cases}.json`.
- `docs/evidence/linear/RAY-117/{README.md,issue-snapshot.json,user-provided-sensor-geometry-20260721.png,sensor-geometry-reconciliation.json,pytest-results.xml,pytest-full-regression-results.xml}`.

**Modify**

- `docs/algorithm/standard-physical-input-contract.md` — state the upstream board-coordinate contract and baseline semantics.
- `docs/algorithm/README.md` — link the schema, fixtures, and evidence.

**Do not modify**

- `client/device/protocol.py`, acquisition, serial transport, parser, simulator byte rules.
- `client/startup_validation/**` (RAY-113-owned production baseline capture/integration).
- UI, app flow, analysis, reporting, cloud, spool, encryption, or authentication code.

## Task-by-task implementation plan

### Task 1 — establish execution/evidence gate and Linear state

1. Re-read Linear project, RAY-117, and RAY-78. Confirm RAY-117 is Backlog, its P0/milestone/dependency status has not changed, and RAY-78 remains insufficient for count-to-force semantics. Report any conflict before a mutation.
2. Verify the project-owned `./scripts/local-env.sh` gate exists in the working tree. If it is absent, stop and report the missing required environment gate; do not copy a possibly divergent environment from another checkout.
3. When implementation is authorized, move only RAY-117 to `In Progress`, post a start comment that states: physical-board output only; no ML/AP; 7.99 mm grid; 5-second PASS baseline used for zero/noise only; no fabricated N/Pa; baseline-window production integration remains RAY-113-dependent. Re-read and save the issue snapshot.
4. Preserve the user-supplied image and SHA-256 in issue evidence. Record `pitch_x_mm: 7.99`, `pitch_y_mm: 7.99`, last centre `(503.37, 375.53)`, source 7 mm metadata status superseded, and `board_coordinate_status: USER_CONFIRMED`.

### Task 2 — write immutable contract tests, then models

1. Add failing tests for valid/invalid sessions: duplicated point/source index, non-finite coordinates, non-positive declared nominal area, vector-length mismatch, non-increasing time, invalid raw value, and non-finite N.
2. Add immutable types: `PhysicalArraySession`, `PhysicalArrayCell`, `PhysicalArrayFrame`, `UnloadedBaselineWindow`, `BaselineReference`, `MeasurementProfile`, `MeasurementUncertainty`, `AdapterProvenance`, and `StandardizationOutcome`.
3. `PhysicalArrayFrame` carries per-cell `raw_count`, `zero_corrected_count`, `relative_load_count`, optional `normal_force_n`, optional uncertainty, frame quality, and flags. Raw-only or relative-only frames always have `normal_force_n = null`.
4. Require schema/profile/geometry/baseline/source versions and provenance hashes. Confirm immutability and focused tests through `./scripts/local-env.sh python -m pytest`.

### Task 3 — implement generic geometry and ports

1. Add failing tests for regular unequal-pitch grids, arbitrary irregular coordinates, rotations/mirrors expressed explicitly in input layout, missing/excluded points, source-index order, and the DO-P4864 grid.
2. Implement generic `BoardCoordinateLayout` and `PhysicalArrayAdapter` protocol. It accepts explicit point cells, not an implicit 48 x 64 shape.
3. Implement `BoardCoordinateFrame.top_left_grid(rows, columns, pitch_x_mm, pitch_y_mm, origin_x_mm=0, origin_y_mm=0)` for adapters that use a regular top-left layout.
4. Test that DO-P4864 point `source_index=99` maps by `row = 99 % 48`, `column = 99 // 48`, with `x = column * 7.99`, `y = row * 7.99`.

### Task 4 — implement baseline profiling and zero correction

1. Add a fixture with an actual 5-second PASS window, nonuniform timestamps, per-cell offsets/noise, plus malformed, loaded, incomplete, non-PASS, and layout-mismatch cases.
2. Write failing tests that baseline derivation uses the robust median and MAD formula above; preserves raw input; reports a layout mismatch; rejects incomplete/non-PASS windows; and attaches all source versions/digests.
3. Implement `build_baseline_reference(window)` and `apply_zero_reference(current_frame, reference)`. The latter creates a new output vector, retains signed residuals, and derives nonnegative relative load values.
4. Surface baseline quality in every affected frame. No device-specific noise cutoff is introduced outside the passed RAY-113 profile.

### Task 5 — standardize arbitrary arrays and quality/time behavior

1. Create regular and irregular fixtures with arbitrary counts, nonuniform coordinates, bad/missing/saturated cells, dropped samples, and nonuniform time.
2. Write failing tests for raw immutability, actual timestamp conversion, baseline-corrected positioning, excluded-cell handling, long interval flags, and invalid duplicate/descending time.
3. Implement the generic adapter: it always emits raw values; it emits zero-corrected and relative-load values only for a layout-matched verified baseline. It emits force in N only for an explicitly force-validated known-load profile; otherwise force is null plus `FORCE_UNCALIBRATED`.
4. No original count is called N, Pa, or a true pressure. Nominal 36 mm2 remains metadata with `ACTIVE_AREA_UNVALIDATED` until electrical active-area verification.

### Task 6 — implement the DO-P4864 decoded-frame adapter

1. Write failing tests built directly from decoded `RawFrame`, never serial bytes.
2. Implement its 48 x 64 declaration with `x = column * 7.99`, `y = row * 7.99`, `source_index = column * 48 + row`, and source flattening `values.reshape(-1, order="F")`.
3. Pass the 5-second `UnloadedBaselineWindow` only through the RAY-117 port. If no qualifying window is available, return a degraded raw-coordinate session with explicit baseline/force/area flags; do not use `DeviceValidationRun` statistics as substitute point offsets.
4. Preserve candidate checksum status as a source-quality observation; never make it a mandatory frame-drop rule. Run adapter tests plus unchanged protocol tests.

### Task 7 — schema, boundaries, evidence, and review state

1. Create a Draft 2020-12 JSON schema with `$id = "physical-array-session/1.0"`, no additional properties, and no body/clinical fields.
2. Update the physical-input contract to distinguish `physical-array-session/1.0` (board coordinates and relative values) from a later body semantic/pressure contract.
3. Add AST/text boundary tests that prohibit UI, cloud, analysis, spool, serial, and device-parser imports from the generic layer; the thin DO adapter may import only the decoded frame type.
4. Run focused and full test suites via `./scripts/local-env.sh python -m pytest`, write JUnit evidence, run `git diff --check`, and document exact results.
5. Post a Linear completion comment and move RAY-117 to `In Review`, never `Done`, until there is real-device evidence for baseline repeatability, known-load force/pressure calibration, active area, saturation/bad-cell thresholds, time uncertainty, and cross-device behavior. Re-read and snapshot the final issue state.

## Acceptance matrix

| Requirement | Planned status |
| --- | --- |
| Versioned generic hardware port and schema | Implement and test |
| Regular/irregular layouts without core 48 x 64 constant | Implement and test |
| Board coordinates, top-left origin, 7.99 mm right/down DO grid | Implement and test |
| 5-second no-load per-cell zero/noise reference | Implement via input port and fixtures |
| Existing RAY-113 production raw-window handoff | Blocked pending RAY-113 contract/provider |
| Spatially located baseline-corrected relative signal | Implement and test |
| Absolute N / Pa | Withheld pending verified known-load calibration |
| ML/AP/COP/displacement/risk/reports | Withheld by user scope |
| Real-device force/repeatability/cross-device validation | Pending; final status In Review |

## Stop conditions

Stop and report if Linear project/issue state conflicts, RAY-78 semantics change, the required local environment gate is missing, the user image cannot be preserved, a change requires serial parsing or RAY-113 workflow edits, a raw/relative value would be labelled as absolute pressure or force, or a body/analysis field leaks into this package.
