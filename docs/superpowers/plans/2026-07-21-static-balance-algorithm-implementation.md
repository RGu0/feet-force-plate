# V1 Static Balance Screening Algorithm Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the approved hardware-independent, rule-first V1 static-balance screening algorithm, versioned recomputation, and customer-safe complete report for adults aged 60 and above.

**Architecture:** A hardware adapter owned by RAY-117 produces `physical-pressure-session/1.0`. The cloud analysis core validates that contract, computes body-coordinate ML/AP features from physical force and real timestamps, grades them against an immutable approved reference artifact, and combines background, completion, and pressure evidence by highest-risk-wins rules. Immutable `AnalysisRun` records all input and algorithm versions; reporting publishes a new `CLOUD_COMPLETE` version under the existing `report_id`. Internal quality, uncertainty, gate, and diagnostic data remain behind explicit private/public model boundaries.

**Tech Stack:** Python 3.11, dataclasses and enums, NumPy, SciPy, SQL migrations, existing cloud port/repository abstractions, Jinja2/Matplotlib PDF generation, pytest, and the repository `./scripts/local-env.sh` uv wrapper.

## Global Constraints

- The approved protocol is exactly four 20-second stages: bilateral feet-together eyes open, bilateral feet-together eyes closed, fixed 90-degree left turn with left foot forward eyes open, and fixed 90-degree left turn with right foot forward eyes open. Preparation and transitions are outside the scored 80 seconds.
- The canonical stage IDs are `BILATERAL_EYES_OPEN`, `BILATERAL_EYES_CLOSED`, `SEMI_TANDEM_LEFT_FORWARD`, and `SEMI_TANDEM_RIGHT_FORWARD`. Correct the abbreviated example in the physical-input document when Task 1 starts; do not support two spellings in production data.
- The core algorithm accepts only force in N, coordinates in mm, area in mm², actual monotonic time in seconds, and `coordinate_frame=SUBJECT_ML_AP`. It never reads device model, row/column count, byte order, raw counts, serial data, or device-specific calibration.
- RAY-117 owns raw-device-to-standard-physical-input conversion and is a dependency, not part of this implementation. Algorithm tests use contract fixtures until the hardware agent supplies adapter evidence.
- V1 is for screening people aged 60 and above. It does not diagnose disease, prescribe treatment, or claim a calibrated future fall probability.
- Risk is rule-first: determine background, completion, and pressure tiers independently; the highest risk wins; only then place the score inside `LOW=80..100`, `MEDIUM=60..79`, or `HIGH=0..59`.
- Explicit high-risk background, inability to complete for balance reasons, staff support, or a clear near-fall can never be averaged away by favorable pressure metrics.
- A technical or protocol invalidity is not evidence that the subject has poor balance. Missing pressure evidence is never converted to zero.
- A production pressure tier requires an immutable, approved reference artifact matched to input schema, measurement-conformance version, uncertainty profile, protocol, feature pipeline, and age band. The gate is default-closed if no exact approved artifact exists.
- Customer models are constructed from an allowlist. Sampling details, bad-cell data, calibration internals, uncertainty, stack traces, storage keys, raw medication text, and diagnostic-package contents never enter the customer report.
- All implementation and verification commands use `./scripts/local-env.sh`; do not use system Python, `pip`, or `pytest`, and do not create a repository-local `.venv`.
- Preserve unrelated dirty-worktree files. Execute this plan in an isolated worktree after the currently untracked environment wrapper and lockfile have been integrated by their owner.
- Automated tests do not complete real-hardware adapter validation, reference-population approval, clinical validation, alert drills, PDF/print inspection, or operator review. Any issue still missing those items remains `In Review`.

## Linear Scope and Execution Order

The Linear project and all assigned issues were re-read before writing this plan. Current issue descriptions for RAY-93 and RAY-94 still contain older hardware-specific `48×64 / ~12 Hz / relative value` language. The approved design instead requires standard physical input and an actual median sample rate of at least 18 Hz. Record this conflict before implementation; do not implement both models.

There is also no assigned issue whose acceptance criteria explicitly own the newly approved background/completion/pressure rule engine and the single 0–100 composite score. Before code execution, create one dedicated issue named `V1 静态平衡筛查规则引擎与综合评分` and make it depend on RAY-117 and block RAY-95. If project governance prefers not to add an issue, update RAY-93 acceptance criteria explicitly before changing its code. Do not silently broaden RAY-93.

Execute one bounded issue at a time in this order:

1. RAY-117 — external hardware-agent dependency; consume only its versioned contract and evidence.
2. New scoring issue or explicitly expanded RAY-93 — approved rules, score bands, and reference artifact gate.
3. RAY-102 — canonical input consumer, versioned feature pipeline, immutable `AnalysisRun`, and recomputation.
4. RAY-93 — hardware-independent capability gates and release/validation status.
5. RAY-94 — approved physical metrics and customer-safe curves.
6. RAY-95 — unified `CLOUD_COMPLETE` report version and PDF/print artifact.
7. RAY-103 — algorithm failure telemetry, SLI/alerts, and sanitized support diagnostics.

When an issue actually starts, move it to `In Progress`, add the implementation/evidence-path comment, and re-read it. After automated evidence but before missing hardware/manual/clinical work, move it to `In Review`, comment the exact missing evidence, and re-read it. Mark `Done` only when every acceptance item is evidenced.

---

### Task 0: Prepare a clean integration baseline

**Files:**
- Reuse after integration: `scripts/local-env.sh`
- Reuse after integration: `pyproject.toml`
- Reuse after integration: `uv.lock`
- Import from branch `codex/task-d-cloud-analysis-reporting`: `cloud/analysis/**`
- Import from branch `codex/task-d-cloud-analysis-reporting`: `cloud/reporting/**`
- Import from branch `codex/task-d-cloud-analysis-reporting`: `cloud/observability/**`
- Import from branch `codex/task-d-cloud-analysis-reporting`: `tests/cloud/**`

- [ ] **Step 1: Create an isolated implementation worktree from the current approved integration branch**

Use the `superpowers:using-git-worktrees` skill. Do not switch or clean the dirty shared `master` worktree.

- [ ] **Step 2: Confirm the repository environment is committed and usable in that worktree**

Run:

```bash
./scripts/local-env.sh python -c "import numpy, scipy; print('cloud algorithm environment ready')"
```

Expected: exits zero and prints `cloud algorithm environment ready`. If the wrapper, project file, or lockfile is absent, stop and record the environment-owner dependency; do not recreate a parallel environment.

- [ ] **Step 3: Import the existing Task D cloud foundation without changing its history**

Merge or cherry-pick the cloud foundation commits `7b8ebb0` and `200d36d` into the isolated worktree, then resolve only files owned by Task D. Do not import stale conclusions from their evidence as current validation.

- [ ] **Step 4: Run the imported baseline tests**

Run:

```bash
./scripts/local-env.sh python -m pytest tests/cloud -q
```

Expected: the imported cloud suite passes before the physical-input refactor. Save the output as the baseline log for the first issue that starts.

- [ ] **Step 5: Commit only integration conflict resolutions, if any**

```bash
git add cloud tests/cloud
git commit -m "Integrate cloud analysis reporting foundation"
```

Skip this commit if the branch import is already present without resolutions.

---

### Task 1: Consume and strictly validate the standard physical input

**Linear:** RAY-102, blocked for real-adapter evidence by RAY-117.

**Files:**
- Create: `cloud/analysis/physical_input.py`
- Modify: `cloud/analysis/models.py`
- Modify: `docs/algorithm/standard-physical-input-contract.md`
- Create: `tests/cloud/analysis/test_physical_input.py`
- Create: `tests/cloud/fixtures/physical_sessions.py`

**Public interfaces:**

```python
class InputValidationError(ValueError): ...

def parse_physical_pressure_session(payload: Mapping[str, object]) -> PhysicalPressureSession: ...
def validate_physical_pressure_session(session: PhysicalPressureSession) -> None: ...
```

- [ ] **Step 1: Write failing contract tests**

Cover a valid irregular non-rectangular array and rejection of:

- the wrong schema or coordinate frame;
- any unit other than mm, N, mm², and s;
- duplicate cells, non-finite geometry, non-positive active area, or mismatched force-vector length;
- non-finite or negative force;
- non-increasing timestamps or stage bounds outside the frame time domain;
- an unknown stage ID, wrong orientation/front-foot combination, or a missing completion record;
- any physical, timing, or coordinate validation status other than `VALIDATED` for a formal input.

Representative assertion:

```python
def test_contract_accepts_irregular_layout_without_device_metadata():
    session = parse_physical_pressure_session(irregular_physical_session_payload())
    assert session.schema_version == "physical-pressure-session/1.0"
    assert session.coordinate_frame is CoordinateFrame.SUBJECT_ML_AP
    assert not hasattr(session, "device_model")
    assert len(session.frames[0].normal_force_n) == len(session.cells)
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
./scripts/local-env.sh python -m pytest tests/cloud/analysis/test_physical_input.py -q
```

Expected: collection fails because `cloud.analysis.physical_input` does not exist.

- [ ] **Step 3: Implement immutable standard-input models and validation**

Use frozen, slotted dataclasses and explicit enums. The model must include:

```python
@dataclass(frozen=True, slots=True)
class MeasurementProfile:
    profile_version: str
    measurement_conformance_version: str
    uncertainty_profile_version: str
    physical_validation: ValidationState
    timing_validation: ValidationState
    coordinate_validation: ValidationState

@dataclass(frozen=True, slots=True)
class SensorCell:
    cell_id: str
    ml_mm: float
    ap_mm: float
    active_area_mm2: float
    status: CellStatus

@dataclass(frozen=True, slots=True)
class PhysicalFrame:
    timestamp_s: float
    normal_force_n: tuple[float, ...]
    quality: FrameQuality

@dataclass(frozen=True, slots=True)
class StageWindow:
    stage_id: StageId
    start_s: float
    end_s: float
    completion_status: CompletionStatus
    actual_completion_s: float
    subject_orientation: SubjectOrientation
    forward_foot: ForwardFoot
    step_count: int
    moved_feet: bool
    touched_rail: bool
    staff_supported: bool
    near_fall: bool
    eyes_opened_early: bool
    stop_reason: StopReason

@dataclass(frozen=True, slots=True)
class PhysicalPressureSession:
    schema_version: str
    session_id: UUID
    coordinate_frame: CoordinateFrame
    coordinate_unit: str
    force_unit: str
    area_unit: str
    time_unit: str
    measurement_profile: MeasurementProfile
    cells: tuple[SensorCell, ...]
    stages: tuple[StageWindow, ...]
    frames: tuple[PhysicalFrame, ...]
```

Reject unknown fields at the external payload boundary so device metadata cannot leak into the algorithm by accident. Preserve `EXCLUDED` cells but omit their forces from all calculations.

- [ ] **Step 4: Correct the contract example to the canonical stage IDs and required fields**

Update only the algorithm contract example and stage table. Do not edit device parsing or client workflow documents.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run:

```bash
./scripts/local-env.sh python -m pytest tests/cloud/analysis/test_physical_input.py -q
```

Expected: all contract tests pass.

- [ ] **Step 6: Commit the contract-consumer slice**

```bash
git add cloud/analysis/physical_input.py cloud/analysis/models.py docs/algorithm/standard-physical-input-contract.md tests/cloud/analysis/test_physical_input.py tests/cloud/fixtures/physical_sessions.py
git commit -m "Add standard physical session consumer"
```

---

### Task 2: Replace hardware-model gates with measurement-capability gates

**Linear:** RAY-93.

**Files:**
- Modify: `cloud/analysis/catalog.py`
- Modify: `cloud/analysis/gates.py`
- Modify: `cloud/analysis/models.py`
- Modify: `tests/cloud/analysis/test_capability_gate.py`

**Public interface:**

```python
def evaluate_capability(
    descriptor: AlgorithmDescriptor,
    session: PhysicalPressureSession,
) -> CapabilityDecision: ...
```

- [ ] **Step 1: Replace stale gate tests with physical-capability cases**

Assert that a descriptor no longer has `supported_device_models` or calibration rank. Test exact rejection/degradation reasons for schema mismatch, unvalidated physical/timing/coordinate input, measurement-conformance mismatch, uncertainty-profile mismatch, insufficient median rate, excessive gap, insufficient duration, low valid-frame ratio, and edge-contact invalidity.

```python
def test_same_physical_capability_is_independent_of_array_layout():
    first = evaluate_capability(descriptor, compact_layout_session())
    second = evaluate_capability(descriptor, sparse_layout_session())
    assert first.status is CapabilityStatus.SUPPORTED
    assert second.status is CapabilityStatus.SUPPORTED
```

- [ ] **Step 2: Run tests and verify RED against the old device-model gate**

Run:

```bash
./scripts/local-env.sh python -m pytest tests/cloud/analysis/test_capability_gate.py -q
```

Expected: failures show that the old descriptor still requires a device model/calibration level.

- [ ] **Step 3: Implement the V1 descriptor and quality decision**

```python
@dataclass(frozen=True, slots=True)
class AlgorithmDescriptor:
    algorithm_id: str = "static-balance-fall-screen"
    algorithm_version: str = "fall-screen-rule-set/1.0"
    input_schema_version: str = "physical-pressure-session/1.0"
    protocol_version: str = "static-balance-fall-screen/1.0"
    feature_pipeline_version: str = "static-balance-feature-pipeline/1.0"
    minimum_median_sample_rate_hz: float = 18.0
    minimum_completed_stage_duration_s: float = 19.0
    minimum_valid_frame_ratio: float = 0.95
    maximum_gap_nominal_intervals: float = 2.0
    release_status: ReleaseStatus = ReleaseStatus.SCREENING_APPROVED
    evidence_status: EvidenceStatus = EvidenceStatus.PRELIMINARY_RULE_BASED
```

Compute median rate from actual timestamp deltas. Keep internal reason codes in `CapabilityDecision.private_reasons`; expose only `SUPPORTED`, `DEGRADED`, `INVALID`, or `UNSUPPORTED` to downstream public-result construction.

- [ ] **Step 4: Make release status default-closed**

Only `SCREENING_APPROVED` descriptors may create customer-reportable results. `DRAFT`, `SHADOW`, and `RETIRED` may generate internal `AnalysisRun` artifacts but cannot publish `CLOUD_COMPLETE`.

- [ ] **Step 5: Run focused and imported compatibility tests**

```bash
./scripts/local-env.sh python -m pytest tests/cloud/analysis/test_capability_gate.py tests/cloud/analysis/test_algorithm_catalog.py -q
```

Expected: all gate/catalog tests pass and contain no device-model assertions.

- [ ] **Step 6: Commit the gate slice**

```bash
git add cloud/analysis/catalog.py cloud/analysis/gates.py cloud/analysis/models.py tests/cloud/analysis/test_capability_gate.py tests/cloud/analysis/test_algorithm_catalog.py
git commit -m "Gate analysis by physical measurement capability"
```

---

### Task 3: Implement the versioned stage-aware physical feature pipeline

**Linear:** RAY-102 and RAY-94.

**Files:**
- Rewrite: `cloud/analysis/features.py`
- Create: `cloud/analysis/feature_parameters.py`
- Create: `tests/cloud/analysis/test_physical_features.py`
- Create: `tests/cloud/analysis/test_cross_array_equivalence.py`

**Public interface:**

```python
def extract_features(
    session: PhysicalPressureSession,
    parameters: FeatureParameters,
) -> SessionFeatureSet: ...
```

- [ ] **Step 1: Write analytic fixture tests before implementation**

Build small physical-force fixtures with closed-form COP locations and trajectories. Assert:

- force-weighted ML/AP COP in mm;
- total path and ML/AP path in mm;
- mean, ML, and AP velocity in mm/s using actual timestamps;
- ML/AP RMS, P95-P5 robust ranges, and 95% ellipse area in mm²;
- total-force coefficient of variation and active contact-area variation;
- EO/EC ratios and changes;
- each semi-tandem-to-EO ratio, worse-side result, and symmetric left/right difference;
- no interpolation or path segment across a gap above two nominal intervals;
- the same physical trajectory expressed by two different sensor layouts produces equal results within `1e-6` for analytic fixtures and an approved fixture tolerance for adapter-derived data.

```python
def test_cross_array_equivalence_uses_physics_not_shape():
    a = extract_features(rectangular_layout_same_field(), params)
    b = extract_features(irregular_layout_same_field(), params)
    assert a.stage(StageId.BILATERAL_EYES_OPEN).mean_velocity_mm_s == pytest.approx(
        b.stage(StageId.BILATERAL_EYES_OPEN).mean_velocity_mm_s,
        abs=1e-6,
    )
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
./scripts/local-env.sh python -m pytest tests/cloud/analysis/test_physical_features.py tests/cloud/analysis/test_cross_array_equivalence.py -q
```

Expected: failures show the imported pipeline still assumes 48×64 raw integer frames and sensor-cell coordinates.

- [ ] **Step 3: Implement versioned preprocessing parameters**

```python
@dataclass(frozen=True, slots=True)
class FeatureParameters:
    version: str = "static-balance-feature-parameters/1.0"
    minimum_total_force_n: float = 50.0
    contact_cell_force_threshold_n: float = 1.0
    despike_window_samples: int = 3
    lowpass_order: int = 4
    lowpass_cutoff_hz: float = 5.0
    maximum_gap_nominal_intervals: float = 2.0
    ratio_epsilon: float = 1e-9
```

The numeric values are versioned engineering parameters, not medical thresholds. Resample only inside contiguous segments onto the segment median interval for zero-phase filtering; never bridge a gap above the maximum. Compute completion time from workflow evidence, not inferred force duration.

- [ ] **Step 4: Implement COP and stage feature calculation**

For every valid frame with total force above the threshold:

```python
total_force_n = force.sum()
cop_ml_mm = float(np.dot(force, cell_ml_mm) / total_force_n)
cop_ap_mm = float(np.dot(force, cell_ap_mm) / total_force_n)
contact_area_mm2 = float(cell_area_mm2[force >= threshold].sum())
```

For filtered body-coordinate points `x=ML`, `y=AP`:

```python
delta = np.diff(np.column_stack((x, y)), axis=0)
path_mm = float(np.linalg.norm(delta, axis=1).sum())
duration_s = float(timestamp_s[-1] - timestamp_s[0])
ellipse_area_95_mm2 = float(np.pi * 5.991 * np.sqrt(max(np.linalg.det(np.cov(x, y)), 0.0)))
```

Use population RMS around each coordinate mean, empirical P5/P95, and actual stage duration. Return explicit unavailable reasons privately when a metric cannot be calculated; never emit NaN in persisted public features.

- [ ] **Step 5: Implement derived comparisons with semantic IDs**

Create derived feature records for each approved metric. Semi-tandem side difference is:

```python
abs(left - right) / max((abs(left) + abs(right)) / 2.0, epsilon)
```

Do not calculate gait cycles, impacts, spectra, entropy, fractals, disease probability, or any metric not approved in the algorithm document.

- [ ] **Step 6: Run feature tests and verify GREEN**

```bash
./scripts/local-env.sh python -m pytest tests/cloud/analysis/test_physical_features.py tests/cloud/analysis/test_cross_array_equivalence.py -q
```

Expected: all analytic, timestamp, gap, stage-comparison, and cross-layout tests pass.

- [ ] **Step 7: Commit the feature slice**

```bash
git add cloud/analysis/features.py cloud/analysis/feature_parameters.py tests/cloud/analysis/test_physical_features.py tests/cloud/analysis/test_cross_array_equivalence.py
git commit -m "Compute static balance features in physical coordinates"
```

---

### Task 4: Add immutable reference artifacts and pressure-domain grading

**Linear:** new scoring issue or expanded RAY-93.

**Files:**
- Create: `cloud/analysis/reference.py`
- Create: `cloud/analysis/pressure_grading.py`
- Create: `tests/cloud/analysis/test_reference_artifact.py`
- Create: `tests/cloud/analysis/test_pressure_grading.py`

**Public interfaces:**

```python
def select_reference_artifact(session, descriptor, artifacts) -> ReferencePopulationArtifact: ...
def grade_pressure(features, artifact) -> PressureAssessment: ...
```

- [ ] **Step 1: Write failing artifact-integrity and default-closed tests**

Test exact version matching, SHA-256 verification of canonical serialized content, immutable empirical distributions, age-band selection (`60-69`, `70-79`, `80+`), explicitly approved fallback to `60+`, approval timestamp, approval identity, sample-inclusion rule version, and repeatability limits. Missing, mismatched, unsigned, mutable, or unapproved artifacts must prevent formal pressure grading.

- [ ] **Step 2: Write failing percentile and domain-rule tests**

For metrics where larger means worse, assert:

- `<=P75`: normal;
- `P75..P90`: mild;
- `P90..P97.5`: moderate;
- `>P97.5`: marked;
- performance mapping knots `(P0,100)`, `(P50,90)`, `(P75,80)`, `(P90,60)`, `(P97.5,30)`, `(P100,0)` with linear interpolation.

Use these frozen primary metrics:

| Domain | Primary metrics |
|---|---|
| Baseline sway | EO mean velocity, ML RMS, AP RMS, ellipse area |
| Eyes-closed change | EC/EO mean-velocity ratio, ML-RMS ratio, AP-RMS ratio, ellipse-area ratio |
| Semi-tandem challenge | worse-side/EO mean-velocity ratio, ML-RMS ratio, ML robust-range ratio, ellipse-area ratio |
| Lead-foot difference | symmetric difference in mean velocity, ML RMS, ML robust range, ellipse area |

Domain rules are exact: any marked metric or at least two moderate metrics gives `MARKED`; any moderate metric or at least two mild metrics gives `MODERATE`; one mild gives `MILD`; otherwise `NORMAL`. The domain continuous score is the median metric score clamped to `NORMAL=80..100`, `MILD=80..89`, `MODERATE=60..79`, or `MARKED=0..59`.

- [ ] **Step 3: Run tests and verify RED**

```bash
./scripts/local-env.sh python -m pytest tests/cloud/analysis/test_reference_artifact.py tests/cloud/analysis/test_pressure_grading.py -q
```

Expected: collection fails because the reference and grading modules do not exist.

- [ ] **Step 4: Implement canonical frozen artifacts and empirical percentiles**

```python
@dataclass(frozen=True, slots=True)
class ReferencePopulationArtifact:
    reference_population_id: str
    input_schema_version: str
    measurement_conformance_version: str
    uncertainty_profile_version: str
    protocol_version: str
    feature_pipeline_version: str
    age_band: AgeBand
    sample_inclusion_rules_version: str
    metric_distributions: Mapping[str, tuple[float, ...]]
    repeatability_limits: Mapping[str, float]
    artifact_sha256: str
    approved_at: datetime
    approved_by: str
```

Copy mappings into immutable sorted tuples at construction. Calculate empirical abnormal percentile with `bisect_right(sorted_values, value) / len(sorted_values)` and preserve the artifact ID/hash on every pressure result.

- [ ] **Step 5: Implement sufficiency and pressure-tier rules**

Formal pressure grading requires baseline, eyes-closed, and semi-tandem domains. The lead-foot-difference domain is included only when both semi-tandem stages have valid metric evidence and their observed difference exceeds the artifact repeatability limit. A balance failure is handled by completion rules, not converted to an extreme pressure percentile.

Across domains:

- no moderate/marked domain and at most one mild domain → `GOOD` / low;
- one moderate domain or at least two mild domains → `CONCERN` / medium;
- any marked domain or at least two moderate domains → `POOR` / high.

The pressure candidate is the lowest trustworthy domain score, then clamped to `GOOD=80..100`, `CONCERN=60..79`, or `POOR=0..59`.

- [ ] **Step 6: Run tests and verify GREEN**

```bash
./scripts/local-env.sh python -m pytest tests/cloud/analysis/test_reference_artifact.py tests/cloud/analysis/test_pressure_grading.py -q
```

Expected: all artifact, percentile, sufficiency, repeatability, domain, and pressure-tier tests pass.

- [ ] **Step 7: Commit the reference/grading slice**

```bash
git add cloud/analysis/reference.py cloud/analysis/pressure_grading.py tests/cloud/analysis/test_reference_artifact.py tests/cloud/analysis/test_pressure_grading.py
git commit -m "Add frozen reference pressure grading"
```

---

### Task 5: Implement background, completion, and composite screening rules

**Linear:** new scoring issue or explicitly expanded RAY-93.

**Files:**
- Create: `cloud/analysis/risk_models.py`
- Create: `cloud/analysis/risk_rules.py`
- Create: `tests/cloud/analysis/test_background_rules.py`
- Create: `tests/cloud/analysis/test_completion_rules.py`
- Create: `tests/cloud/analysis/test_composite_score.py`

**Public interface:**

```python
def assess_screening_risk(
    age_years: int | None,
    background: BackgroundRiskInput,
    stages: tuple[StageWindow, ...],
    pressure: PressureAssessment | None,
) -> ScreeningResult: ...
```

- [ ] **Step 1: Write the complete decision-table tests**

Background high cases:

- at least two falls in 12 months;
- any fall with injury/medical care;
- prolonged inability to rise after a fall;
- loss of consciousness, syncope, or near-syncope;
- recurrent dizziness that affects standing/walking or occurs on rising.

Two or more explicit high facts, or a same-day stop symptom, use the severe cap of 39. One explicit high fact caps at 59. General background facts cap at 79. Medication category tags never trigger high alone; conditional medication categories count only with dizziness, orthostatic symptoms, drowsiness, or slowed reaction. `UNKNOWN`, `DECLINED`, and `NOT_COLLECTED` are never interpreted as negative.

Completion high cases:

- two or more balance failures;
- eyes-closed and either semi-tandem stage both fail;
- both semi-tandem stages fail;
- bilateral eyes-open cannot be safely completed;
- staff support or a clear near-fall.

One semi-tandem balance failure with all other stages completed is at least medium; it becomes high when support, near-fall, or another clear abnormality exists. `TECHNICAL_INVALID`, `PROTOCOL_INVALID`, and `NON_BALANCE_STOP` do not themselves raise risk.

- [ ] **Step 2: Add invariant/property tests for the final score**

```python
@pytest.mark.parametrize("background,completion,pressure", all_rule_combinations())
def test_score_never_contradicts_overall_tier(background, completion, pressure):
    result = combine(background, completion, pressure)
    if result.overall_risk_level is RiskLevel.LOW:
        assert 80 <= result.overall_screening_score <= 100
    elif result.overall_risk_level is RiskLevel.MEDIUM:
        assert 60 <= result.overall_screening_score <= 79
    elif result.overall_risk_level is RiskLevel.HIGH:
        assert 0 <= result.overall_screening_score <= 59
```

Also assert that favorable pressure cannot lift a background/completion cap; technical invalidity cannot create high risk; pressure absence produces no zero; age below 60 or unknown produces no older-adult composite rating; and the same complete input produces byte-identical canonical result JSON.

- [ ] **Step 3: Run tests and verify RED**

```bash
./scripts/local-env.sh python -m pytest tests/cloud/analysis/test_background_rules.py tests/cloud/analysis/test_completion_rules.py tests/cloud/analysis/test_composite_score.py -q
```

Expected: collection fails because the rule modules do not exist.

- [ ] **Step 4: Implement typed questionnaire inputs without free text**

Use explicit enums for every required answer and medication category. The model stores only category tags and collection status; it has no medication-name, dose, prescription-image, or free-text field.

```python
class RiskLevel(IntEnum):
    LOW = 0
    MEDIUM = 1
    HIGH = 2

@dataclass(frozen=True, slots=True)
class RouteAssessment:
    risk_level: RiskLevel | None
    score_cap: int | None
    public_evidence: tuple[PublicEvidenceCode, ...]
    assessable: bool
```

- [ ] **Step 5: Implement highest-risk-wins and score clamping**

```python
available_routes = tuple(route for route in routes if route.assessable)
overall_tier = max(route.risk_level for route in available_routes if route.risk_level is not None)
score_candidates = [route.score_cap for route in available_routes if route.score_cap is not None]
if pressure is not None and pressure.assessable:
    score_candidates.append(pressure.candidate_score)
raw_score = min(score_candidates)
final_score = clamp_to_band(raw_score, overall_tier)
```

If pressure is unavailable but background or completion independently establishes medium/high, return `PARTIAL_HIGH_RISK` with the applicable cap. If no route can establish a trustworthy result, return `NOT_ASSESSABLE` without a numeric score. A fully low-risk result requires assessable pressure plus complete background and completion inputs.

- [ ] **Step 6: Build a strict public result projection**

`ScreeningResult` carries only `overall_risk_level`, `overall_screening_score`, `result_status`, approved background labels, completion summary, domain results, key findings, recommended-action code, and version references. Private rule traces are stored in a separate internal artifact keyed by `analysis_run_id` and are not serializable through the public report builder.

- [ ] **Step 7: Run the rule suite and verify GREEN**

```bash
./scripts/local-env.sh python -m pytest tests/cloud/analysis/test_background_rules.py tests/cloud/analysis/test_completion_rules.py tests/cloud/analysis/test_composite_score.py -q
```

Expected: all decision-table, missing-evidence, age-gate, determinism, and invariant tests pass.

- [ ] **Step 8: Commit the rules slice**

```bash
git add cloud/analysis/risk_models.py cloud/analysis/risk_rules.py tests/cloud/analysis/test_background_rules.py tests/cloud/analysis/test_completion_rules.py tests/cloud/analysis/test_composite_score.py
git commit -m "Add rule-first static balance screening score"
```

---

### Task 6: Version `AnalysisRun`, recomputation, and persistence

**Linear:** RAY-102.

**Files:**
- Modify: `cloud/analysis/models.py`
- Modify: `cloud/analysis/ports.py`
- Modify: `cloud/analysis/orchestrator.py`
- Create: `cloud/analysis/migrations/0002_static_balance_v1.sql`
- Modify: `tests/cloud/analysis/test_orchestrator.py`
- Create: `tests/cloud/analysis/test_recompute.py`
- Create: `tests/cloud/analysis/test_analysis_migration.py`

**Ports:**

```python
class StandardPhysicalSessionLoader(Protocol):
    def load(self, complete_manifest: CompleteSessionManifest, adapter_version: str) -> PhysicalPressureSession: ...

class ReferenceArtifactRepository(Protocol):
    def get_approved(self, selector: ReferenceSelector) -> ReferencePopulationArtifact | None: ...
```

- [ ] **Step 1: Write failing idempotency and recomputation tests**

Assert that:

- only a complete-session event can start analysis;
- the cloud rebuilds standard input through the version-pinned loader and never trusts client-derived features;
- identical manifest plus all version/hash fields returns the same immutable run;
- changing input schema, adapter, measurement conformance, uncertainty, protocol, feature pipeline, feature parameters, rule set, reference population, or questionnaire snapshot creates a new run;
- a failed run persists a safe error record and can be retried as a new attempt without overwriting history;
- completion is committed only after feature, rule, and public-result artifacts persist successfully.

- [ ] **Step 2: Run tests and verify RED**

```bash
./scripts/local-env.sh python -m pytest tests/cloud/analysis/test_orchestrator.py tests/cloud/analysis/test_recompute.py tests/cloud/analysis/test_analysis_migration.py -q
```

Expected: failures show that the old run key contains raw payload/calibration/device assumptions and lacks the newly required versions.

- [ ] **Step 3: Define the immutable run identity**

Persist at least:

```text
session_id
input_manifest_sha256
hardware_adapter_version
input_schema_version
measurement_conformance_version
uncertainty_profile_version
test_protocol_version
feature_pipeline_version
feature_parameters_sha256
rule_set_version
reference_population_id
reference_artifact_sha256
questionnaire_snapshot_sha256
result_schema_version
capability_status
```

Canonicalize all hashes with sorted-key UTF-8 JSON and reject non-finite numeric values before hashing.

- [ ] **Step 4: Refactor the orchestrator into explicit stages**

```python
manifest = manifest_repo.get_complete(event.session_id)
physical_session = physical_loader.load(manifest, requested.adapter_version)
capability = evaluate_capability(descriptor, physical_session)
features = extract_features(physical_session, feature_parameters)
reference = reference_repo.get_approved(reference_selector(...))
pressure = grade_pressure(features, reference) if reference is not None else None
result = assess_screening_risk(age, background, physical_session.stages, pressure)
repository.complete(run_id, features, result, private_trace)
```

Gate failure returns a typed non-publishable result; it does not synthesize metrics. Preserve the existing good persistence-before-completion and idempotent-run patterns where they remain compatible.

- [ ] **Step 5: Add an additive SQL migration**

Create new columns/tables for reference artifacts, feature-parameter hashes, questionnaire snapshot hashes, public screening results, and private rule traces. Enforce uniqueness on the full run identity. Keep public and private JSON in separate columns or tables with separate repository methods. Do not rewrite `0001_analysis.sql` after it has been integrated.

- [ ] **Step 6: Run orchestration and migration tests**

```bash
./scripts/local-env.sh python -m pytest tests/cloud/analysis/test_orchestrator.py tests/cloud/analysis/test_recompute.py tests/cloud/analysis/test_analysis_migration.py -q
```

Expected: all complete-trigger, exact-key idempotency, version-change recompute, transaction, failure, and schema tests pass.

- [ ] **Step 7: Commit the versioned-run slice**

```bash
git add cloud/analysis/models.py cloud/analysis/ports.py cloud/analysis/orchestrator.py cloud/analysis/migrations/0002_static_balance_v1.sql tests/cloud/analysis/test_orchestrator.py tests/cloud/analysis/test_recompute.py tests/cloud/analysis/test_analysis_migration.py
git commit -m "Version static balance analysis recomputation"
```

---

### Task 7: Build customer-safe professional parameters and figures

**Linear:** RAY-94.

**Files:**
- Modify: `cloud/reporting/models.py`
- Modify: `cloud/reporting/builder.py`
- Modify: `cloud/reporting/figures.py` if present after branch integration
- Create: `tests/cloud/reporting/test_static_balance_content.py`
- Create: `tests/cloud/reporting/test_report_privacy.py`

- [ ] **Step 1: Write failing report-content and privacy tests**

Assert that customer content includes:

- one composite 0–100 score and one low/medium/high screening tier;
- the main public evidence and non-diagnostic recommendation;
- all four stage completion states and actual completion times;
- baseline sway, eyes-closed change, semi-tandem challenge, and lead-foot-difference domains;
- approved core metrics with mm, mm/s, and mm² units;
- four body-coordinate ML/AP COP curves with correct axis labels;
- explicit `未完成` or `未评价`, never a fabricated zero.

Assert recursively that serialized report data and rendered HTML contain none of: sample rate, frame gap, bad-cell ratio, calibration internals, uncertainty, device model, stack trace, raw rule trace, object/storage key, medication name, or free-text prescription information.

- [ ] **Step 2: Run tests and verify RED**

```bash
./scripts/local-env.sh python -m pytest tests/cloud/reporting/test_static_balance_content.py tests/cloud/reporting/test_report_privacy.py -q
```

Expected: old reporting models expose relative counts, sensor-cell coordinates, or a second pressure total.

- [ ] **Step 3: Implement explicit public view models**

```python
@dataclass(frozen=True, slots=True)
class CustomerScreeningSummary:
    overall_screening_score: int | None
    overall_risk_level: RiskLevel | None
    result_status: ResultStatus
    primary_basis: str
    recommended_action: str
    non_diagnostic_notice: str
```

The builder must accept only `PublicScreeningResult` and `ReportableFigureData`; its signature must make it impossible to pass an `AnalysisRun` private trace or capability decision directly.

- [ ] **Step 4: Render physical plots without array assumptions**

Plot ML vs AP in mm with equal aspect ratio and consistent body-axis arrows. Time-series plots use real seconds and physical units. Heatmaps, when included, must use supplied physical cell geometry or a pre-rendered reportable artifact; they must not reshape to 48×64.

- [ ] **Step 5: Run content/privacy tests and the reporting suite**

```bash
./scripts/local-env.sh python -m pytest tests/cloud/reporting/test_static_balance_content.py tests/cloud/reporting/test_report_privacy.py tests/cloud/reporting -q
```

Expected: all report content, unit, missing-data, and recursive privacy tests pass.

- [ ] **Step 6: Commit the professional-report slice**

```bash
git add cloud/reporting/models.py cloud/reporting/builder.py cloud/reporting/figures.py tests/cloud/reporting/test_static_balance_content.py tests/cloud/reporting/test_report_privacy.py
git commit -m "Present physical static balance screening results"
```

Omit `cloud/reporting/figures.py` from `git add` if the integrated foundation keeps figure code in `builder.py`.

---

### Task 8: Publish the unified `CLOUD_COMPLETE` report and PDF artifact

**Linear:** RAY-95.

**Files:**
- Modify: `cloud/reporting/service.py`
- Modify: `cloud/reporting/pdf.py`
- Modify: `cloud/reporting/models.py`
- Create: `cloud/reporting/migrations/0002_static_balance_report.sql`
- Modify: `tests/cloud/reporting/test_reporting_service.py`
- Create: `tests/cloud/reporting/test_pdf_artifact.py`

- [ ] **Step 1: Write failing immutable-version tests**

Assert that a publishable completed run creates a new immutable `CLOUD_COMPLETE` version under the existing `report_id`, stores algorithm/reference/run IDs, creates a PDF artifact with content hash and media type, and never overwrites the basic report or an older complete version. A draft, shadow, unsupported, invalid, or missing-reference run must not publish.

- [ ] **Step 2: Run tests and verify RED**

```bash
./scripts/local-env.sh python -m pytest tests/cloud/reporting/test_reporting_service.py tests/cloud/reporting/test_pdf_artifact.py -q
```

Expected: failures identify missing V1 fields and publication gates.

- [ ] **Step 3: Extend the report-version identity and publication transaction**

Persist `report_id`, monotonically increasing report version, `CLOUD_COMPLETE`, `analysis_run_id`, rule set, feature pipeline, reference artifact ID/hash, content hash, generated time, and artifact references. Commit report version and artifact metadata atomically after the PDF bytes have been generated and hashed.

- [ ] **Step 4: Generate deterministic printable PDF content**

Use embedded/local fonts, fixed page sizes, stable chart dimensions, and no external URL fetch. Automated tests verify `%PDF` signature, non-empty pages, expected public text, and absence of denylisted internal terms. Do not claim visual correctness from byte-level tests.

- [ ] **Step 5: Run the reporting suite**

```bash
./scripts/local-env.sh python -m pytest tests/cloud/reporting -q
```

Expected: all immutable version, publication gate, PDF, and privacy tests pass.

- [ ] **Step 6: Perform and record manual PDF/print inspection**

Render at least one low, medium, high, partial-high-risk, and not-assessable sample. Inspect pagination, Chinese font embedding, ML/AP plots, grayscale printing, missing-data language, non-diagnostic notice, and absence of internal quality/debug fields. If no target print environment or reviewer is available, keep RAY-95 `In Review` and record the missing inspection.

- [ ] **Step 7: Commit the unified-report slice**

```bash
git add cloud/reporting/service.py cloud/reporting/pdf.py cloud/reporting/models.py cloud/reporting/migrations/0002_static_balance_report.sql tests/cloud/reporting/test_reporting_service.py tests/cloud/reporting/test_pdf_artifact.py
git commit -m "Publish versioned complete screening reports"
```

---

### Task 9: Add safe algorithm failure telemetry, alerts, and diagnostics

**Linear:** RAY-103.

**Files:**
- Modify: `cloud/observability/events.py`
- Modify: `cloud/observability/metrics.py`
- Modify: `cloud/observability/alerts.py`
- Modify: `cloud/observability/diagnostics.py`
- Modify: `tests/cloud/observability/test_failure_events.py`
- Create: `tests/cloud/observability/test_algorithm_sli.py`
- Create: `tests/cloud/observability/test_diagnostic_privacy.py`

- [ ] **Step 1: Write failure-taxonomy and privacy tests**

Use stable safe reason codes for contract invalid, capability unsupported, reference unavailable, feature failure, rule failure, persistence failure, and report/PDF failure. Assert that automatic events contain only allowlisted identifiers, versions, state, duration, and safe reason codes. Raw force, questionnaire answers, medication categories, names, report contents, exception messages, and stack traces are excluded from remote telemetry.

- [ ] **Step 2: Run tests and verify RED**

```bash
./scripts/local-env.sh python -m pytest tests/cloud/observability/test_failure_events.py tests/cloud/observability/test_algorithm_sli.py tests/cloud/observability/test_diagnostic_privacy.py -q
```

Expected: failures show missing V1 reason codes, SLIs, or diagnostic denylist coverage.

- [ ] **Step 3: Implement algorithm SLIs and alert definitions**

Track counts and latency for complete-session triggers, supported/unsupported decisions, analysis success/failure, reference misses, recomputation, `CLOUD_COMPLETE` publication, and PDF failure. Define alert windows and thresholds in versioned configuration, including sustained analysis failure rate, reference miss after deployment, queue age, and report publication lag. Do not alert on an individual subject's risk tier.

- [ ] **Step 4: Implement sanitized support diagnostic export**

The diagnostic bundle may include safe run/report IDs, version matrix, stage-state enums, gate outcome, error code, event timeline, and integrity hashes. It must exclude raw frames, COP arrays, questionnaire values, medication tags, customer report body, credentials, signed URLs, and object keys. Encrypt and expire the bundle according to the existing RAY-103 design.

- [ ] **Step 5: Run observability tests and stage an alert drill**

```bash
./scripts/local-env.sh python -m pytest tests/cloud/observability -q
```

Expected: all allowlist, SLI, alert-definition, and diagnostic-privacy tests pass. Exercise one synthetic feature failure and one PDF failure in the target monitoring environment. If the monitoring backend or on-call reviewer is unavailable, keep RAY-103 `In Review` and record the missing drill.

- [ ] **Step 6: Commit the observability slice**

```bash
git add cloud/observability/events.py cloud/observability/metrics.py cloud/observability/alerts.py cloud/observability/diagnostics.py tests/cloud/observability/test_failure_events.py tests/cloud/observability/test_algorithm_sli.py tests/cloud/observability/test_diagnostic_privacy.py
git commit -m "Observe static balance analysis safely"
```

---

### Task 10: Verify end to end and deliver issue-local evidence

**Linear:** each issue is handled separately; do not batch status changes.

**Files:**
- Create or update only when its issue is active: `docs/evidence/linear/<ISSUE-ID>/README.md`
- Add issue-local sanitized logs and sample reports under the same directory
- Do not modify a shared evidence index

- [ ] **Step 1: Run all automated cloud tests**

```bash
./scripts/local-env.sh python -m pytest tests/cloud -q
```

Expected: all cloud analysis, reporting, and observability tests pass.

- [ ] **Step 2: Run repository regression tests**

```bash
./scripts/local-env.sh python -m pytest -q
```

Expected: all repository tests pass. If an unrelated pre-existing failure remains, capture its exact command/output and prove the Task D focused suites pass; do not edit another task's files to hide it.

- [ ] **Step 3: Run a sanitized golden-session end-to-end test**

Use synthetic physical fixtures for:

- low risk with complete valid pressure evidence;
- general background medium risk despite good pressure;
- explicit high background despite good pressure;
- multiple balance failures with incomplete pressure evidence;
- poor pressure with no background history;
- technical invalidity with no independent risk evidence;
- same physical motion on two array layouts;
- identical recomputation and changed-version recomputation.

Assert public JSON, report version, PDF hash/artifact metadata, and zero leakage of private data.

- [ ] **Step 4: Update each active issue's evidence README**

Include issue ID/title/URL, capture timestamp, status/milestone/priority, acceptance snapshot, implementation files, decisions, exact commands and outcomes, automated versus hardware/manual/clinical boundaries, limitations, and commit SHA. Evidence fixtures must be synthetic and contain no secrets or customer data.

- [ ] **Step 5: Record unresolved external evidence honestly**

At minimum, keep the affected issues `In Review` until these are complete:

- RAY-117 known-load, coordinate/orientation, timing, and cross-adapter real-hardware evidence;
- approval of a frozen 60+ reference artifact and its age-band sufficiency;
- algorithm/clinical validation on representative older-adult samples and prospective outcomes;
- PDF/print and operator-language review;
- monitoring alert drill and support-diagnostic review.

- [ ] **Step 6: Commit evidence with its owning implementation**

For each issue, stage only its code, tests, migration, and `docs/evidence/linear/<ISSUE-ID>/` directory. Then comment in Linear with the commit SHA, evidence-relative path, automated conclusion, and every unverified item; re-read the issue to confirm the status/comment.

## Required Result Schemas

The implementation is complete only when persisted results can represent these states without ambiguity:

| `result_status` | Score | Meaning |
|---|---:|---|
| `COMPLETE` | 0–100 | Background, completion, and approved pressure evidence support a full result |
| `PARTIAL_HIGH_RISK` | 0–79 | Background or completion independently establishes medium/high risk while pressure is unavailable |
| `NOT_ASSESSABLE` | absent | Evidence cannot support a trustworthy overall result |

Every complete or partial result records protocol, standard-input, measurement-conformance, uncertainty, feature-pipeline, feature-parameter, rule-set, reference-artifact when used, and result-schema versions. Only reportable versions and public evidence labels cross the reporting boundary.

## Explicit Non-Goals

- Raw device parsing, column/row mapping, calibration, physical conversion, and client test-state flow.
- Device-specific algorithm branches or a 48×64 assumption.
- Dynamic gait, gait cycle, impact, spectral, entropy, fractal, or disease-diagnostic metrics.
- A trained medical prediction model or claimed probability of falling.
- Fixed percentage weights that average background, completion, or pressure evidence.
- Online threshold learning or silent mutation of a released reference population.
- Free-text medication collection or customer-visible internal quality/debug data.

## Definition of Algorithm-Implementation Success

Automated implementation success means the same validated physical session and version set deterministically produce the same immutable features, rule result, `AnalysisRun`, customer report content, and PDF artifact metadata; different sensor layouts representing the same physical field agree within approved tolerance; any high-risk rule constrains the score correctly; missing/technical evidence is never treated as poor balance; and public-report/telemetry boundaries pass recursive leakage tests.

This does not by itself establish medical-grade fall prediction. Product release remains a preliminary institutional screening aid until the reference population, target hardware, operator workflow, print output, monitoring drill, and prospective clinical evidence are separately completed and recorded.
