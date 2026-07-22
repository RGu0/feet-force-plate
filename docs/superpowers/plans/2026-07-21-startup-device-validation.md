# Startup Device Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Require every application launch to connect the DO-P4864, collect a fresh continuous five-second unloaded raw-count window, validate it, and block the workbench until the run passes.

**Architecture:** Add a focused `client/startup_validation` package between the existing `ByteTransport`/`DaoOneP4864Parser` boundary and a new startup-only Qt window. The domain service owns monotonic-time collection and versioned raw-count rules; a coordinator owns retries, public state/copy, persistence, and safe telemetry; the packaged entry composes fresh serial transports and parsers for every run. Extend the existing SQLite state boundary additively for auditable validation summaries and a distinct retryable telemetry queue, without storing raw frames or customer identity.

**Tech Stack:** Python 3.11, NumPy, PySide6, SQLite, pytest/pytest-qt, existing `./scripts/local-env.sh` uv wrapper.

## Global Constraints

- Execute in dependency order `RAY-113 -> RAY-114 -> RAY-115`; start and close each Linear issue separately.
- Reuse the production `ByteTransport`, `DaoOneP4864Parser`, and immutable `(48, 64) uint8` `RawFrame` contract; no side-channel decoder.
- A baseline window starts only after a structurally valid unloaded frame and spans at least `5_000_000_000` nanoseconds by `host_monotonic_ns`; never convert five seconds to a frame count.
- `20.7 Hz` is a versioned observed runtime baseline, not a device capability promise; CheckSum, physical units, calibration, and long-term drift remain unconfirmed.
- Every retry creates a new run ID, transport, parser, timer, frame window, and result; partial windows are discarded.
- Network failure never blocks local validation or a passing device from reaching the workbench.
- The operator UI shows no bad-point detail, protocol error, quality threshold, internal curve, raw values, file path, or stack trace.
- Reuse Steady Health colors, typography, spacing, radii, buttons, status assets, header/footer rhythm, and imperative Chinese copy; do not change global navigation.
- Do not modify or revert unrelated dirty-worktree behavior. Changes to `qt_shell.py`, `controller.py`, `state_store.py`, or their tests must be additive and narrowly scoped.
- All Python/test commands use `./scripts/local-env.sh`; no repository-local `.venv`.
- Automated success without real DO-P4864, Windows/high-DPI, operator usability, or telemetry backend integration may only move issues to `In Review`, never `Done`.

---

### Task 1: RAY-113 versioned run model and unloaded baseline rules

**Files:**
- Create: `client/startup_validation/__init__.py`
- Create: `client/startup_validation/models.py`
- Create: `client/startup_validation/rules.py`
- Test: `tests/startup_validation/test_models_and_rules.py`

**Interfaces:**
- Consumes: existing `client.device.protocol.RawFrame` with `(48, 64) uint8`, `host_monotonic_ns`, and audit flags.
- Produces: `ValidationThresholds`, `ValidationReason`, `ValidationOutcome`, `ValidationStatistics`, `DeviceValidationRun`, and `evaluate_baseline(frames, statistics, thresholds)`.

- [ ] **Step 1: Write failing model and rule tests**

```python
def test_run_is_versioned_auditable_and_contains_no_raw_frame_payload():
    run = DeviceValidationRun.passed(...)
    assert run.schema_version == "device-validation-run/1"
    assert run.rules_version == "startup-baseline/1"
    assert "values" not in run.safe_summary()

def test_rule_engine_rejects_rate_gap_fixed_saturation_noise_drift_and_local_faults():
    assert ValidationReason.RATE_OUT_OF_RANGE in evaluate_case("low-rate")
    assert ValidationReason.GAP_TOO_LARGE in evaluate_case("large-gap")
    assert ValidationReason.NO_VARIATION in evaluate_case("unchanged")
    assert ValidationReason.FIXED_VALUE_AREA in evaluate_case("fixed-nonzero")
    assert ValidationReason.SATURATION in evaluate_case("saturated")
    assert ValidationReason.LOCAL_ANOMALY in evaluate_case("local-hotspot")
    assert ValidationReason.NOISE in evaluate_case("noisy")
    assert ValidationReason.DRIFT in evaluate_case("drifting")
```

- [ ] **Step 2: Run tests and verify RED**

Run: `./scripts/local-env.sh python -m pytest tests/startup_validation/test_models_and_rules.py -q`

Expected: collection fails because `client.startup_validation` does not exist.

- [ ] **Step 3: Implement immutable versioned models and raw-count rules**

```python
class ValidationOutcome(StrEnum):
    PASS = "PASS"
    RETRYABLE_FAIL = "RETRYABLE_FAIL"
    SERVICE_REQUIRED = "SERVICE_REQUIRED"

@dataclass(frozen=True, slots=True)
class ValidationThresholds:
    version: str = "startup-baseline/1"
    window_duration_ns: int = 5_000_000_000
    observed_nominal_rate_hz: float = 20.7
    minimum_rate_hz: float = 12.0
    maximum_gap_ns: int = 250_000_000
    unloaded_frame_mean_max: float = 4.0
    unloaded_active_count_max: int = 64
    unloaded_active_threshold: int = 8
    saturation_value: int = 255
    saturation_fraction_max: float = 0.001
    unchanged_sensor_fraction_max: float = 0.995
    fixed_nonzero_fraction_max: float = 0.20
    local_persistent_value_max: float = 32.0
    temporal_noise_p95_max: float = 3.0
    drift_mean_delta_max: float = 2.0
    service_required_after: int = 3
```

`evaluate_baseline` validates shape/dtype first, computes rate and gaps only from host monotonic timestamps, uses raw-count summaries only, returns stable reason codes, and never mutates or calibrates the input arrays.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `./scripts/local-env.sh python -m pytest tests/startup_validation/test_models_and_rules.py -q`

Expected: all Task 1 tests pass.

- [ ] **Step 5: Commit the RAY-113 model/rules slice**

```bash
git add client/startup_validation/__init__.py client/startup_validation/models.py client/startup_validation/rules.py tests/startup_validation/test_models_and_rules.py
git commit -m "Add startup baseline validation rules"
```

### Task 2: RAY-113 five-second production-chain collector

**Files:**
- Create: `client/startup_validation/service.py`
- Test: `tests/startup_validation/test_validation_service.py`
- Modify: `client/device/simulator.py`
- Test: `tests/device/test_simulator.py`

**Interfaces:**
- Consumes: `ByteTransport.read(max_bytes)`, a fresh `DaoOneP4864Parser`, `ValidationThresholds`, and injected `monotonic_ns`/`wall_time_ns` clocks.
- Produces: `DeviceValidationService.run(request, on_progress) -> DeviceValidationRun`; progress phases `WAITING_FOR_EMPTY`, `COLLECTING_BASELINE`, and `VALIDATING`.

- [ ] **Step 1: Write failing collector tests through encoded bytes and the real parser**

```python
def test_window_starts_on_first_valid_unloaded_frame_and_spans_full_five_seconds():
    run = service_with_timestamped_wire_frames(...).run(request)
    assert run.outcome is ValidationOutcome.PASS
    assert run.statistics.end_monotonic_ns - run.statistics.start_monotonic_ns >= 5_000_000_000
    assert run.statistics.valid_frame_count != round(5 * 20.7)

def test_load_disconnect_and_stall_discard_partial_window():
    assert run_case("load").reason is ValidationReason.LOAD_NOT_EMPTY
    assert run_case("disconnect").reason is ValidationReason.STREAM_INTERRUPTED
    assert run_case("stall").reason is ValidationReason.STREAM_INTERRUPTED
    assert run_case("disconnect").window_retained is False

def test_retry_uses_fresh_parser_transport_and_run_id():
    first, second = run_two_attempts()
    assert first.validation_run_id != second.validation_run_id
    assert second.previous_validation_run_id == first.validation_run_id
    assert second.statistics.start_source_index == 0
```

- [ ] **Step 2: Run collector tests and verify RED**

Run: `./scripts/local-env.sh python -m pytest tests/startup_validation/test_validation_service.py tests/device/test_simulator.py -q`

Expected: tests fail because `DeviceValidationService` and deterministic empty-baseline simulator support are absent.

- [ ] **Step 3: Implement monotonic collection and deterministic empty-baseline simulation**

```python
while True:
    chunk = transport.read(read_size)
    for frame in parser.feed(chunk):
        if baseline_start_ns is None:
            if is_obviously_loaded(frame, thresholds):
                return failed_run(ValidationReason.LOAD_NOT_EMPTY, retain_window=False)
            baseline_start_ns = frame.host_monotonic_ns
        frames.append(frame)
        elapsed_ns = frame.host_monotonic_ns - baseline_start_ns
        on_progress(CollectionProgress.collecting(elapsed_ns, thresholds.window_duration_ns))
        if elapsed_ns >= thresholds.window_duration_ns:
            return validate_complete_window(frames)
    if last_valid_frame_age_ns() > thresholds.maximum_gap_ns:
        return failed_run(ValidationReason.STREAM_INTERRUPTED, retain_window=False)
```

The simulator addition is a raw-count `EMPTY_BASELINE` pattern with deterministic low-amplitude temporal variation. It continues to emit wire frames through `encode_frame`; no decoded-frame shortcut is allowed.

- [ ] **Step 4: Run focused and existing device tests and verify GREEN**

Run: `./scripts/local-env.sh python -m pytest tests/startup_validation/test_validation_service.py tests/device/test_protocol.py tests/device/test_simulator.py tests/device/test_acquisition.py -q`

Expected: all selected tests pass with no warnings.

- [ ] **Step 5: Commit the RAY-113 collection slice**

```bash
git add client/startup_validation/service.py client/device/simulator.py tests/startup_validation/test_validation_service.py tests/device/test_simulator.py
git commit -m "Collect five second startup baselines"
```

### Task 3: RAY-113 evidence and Linear handoff

**Files:**
- Create: `docs/evidence/linear/RAY-113/README.md`
- Create: `docs/evidence/linear/RAY-113/issue-snapshot.json`
- Create: `docs/evidence/linear/RAY-113/pytest-results.xml`

**Interfaces:**
- Consumes: fresh Linear RAY-113 snapshot, Task 1–2 commits, and test output.
- Produces: reviewable implementation/verification evidence with automatic/hardware/calibration boundaries.

- [ ] **Step 1: Run the complete RAY-113 automated matrix**

Run: `./scripts/local-env.sh python -m pytest tests/startup_validation/test_models_and_rules.py tests/startup_validation/test_validation_service.py tests/device -q --junitxml=docs/evidence/linear/RAY-113/pytest-results.xml`

Expected: exit 0; evidence records the exact passed count.

- [ ] **Step 2: Write the issue snapshot and evidence README**

The README records issue URL/status/relations, exact commands and outputs, threshold/rule versions, implementation files, red-green history, commit SHAs, and explicitly marks real DO-P4864 multi-start/load/unplug checks plus calibration/unit confirmation as unverified.

- [ ] **Step 3: Verify evidence and commit**

Run: `./scripts/local-env.sh python -m json.tool docs/evidence/linear/RAY-113/issue-snapshot.json >/dev/null && git diff --check`

Expected: exit 0.

```bash
git add docs/evidence/linear/RAY-113
git commit -m "Document RAY-113 validation evidence"
```

- [ ] **Step 4: Update Linear and re-read**

Set RAY-113 to `In Review`; comment with full commit SHA(s), evidence path, exact verification command/result, and unverified hardware/calibration boundaries. Re-read issue status and the new comment before starting RAY-114.

### Task 4: RAY-114 startup state machine and public presentation model

**Files:**
- Create: `client/startup_validation/workflow.py`
- Test: `tests/startup_validation/test_startup_workflow.py`

**Interfaces:**
- Consumes: a connector factory that returns a fresh `(device_ref, ByteTransport, DaoOneP4864Parser)` and `DeviceValidationService`.
- Produces: `StartupValidationState`, `StartupFailure`, `StartupPresentation`, and `StartupValidationCoordinator.run(previous_run_id=None)` with state-transition callbacks.

- [ ] **Step 1: Write failing state-machine tests**

```python
def test_success_path_is_linear_and_workbench_gate_opens_only_after_pass():
    coordinator.run()
    assert observed_states == [BOOTSTRAPPING, CONNECTING, WAITING_FOR_EMPTY, COLLECTING_BASELINE, VALIDATING, PASSED]
    assert coordinator.can_enter_workbench

def test_all_failures_block_workbench_and_expose_one_public_action():
    for failure in StartupFailure:
        presentation = run_failure(failure)
        assert not coordinator.can_enter_workbench
        assert presentation.primary_action in {"重新连接", "关闭占用程序后重试", "清空设备", "重新校验", "重新启动"}
        assert presentation.technical_detail is None
```

- [ ] **Step 2: Run workflow tests and verify RED**

Run: `./scripts/local-env.sh python -m pytest tests/startup_validation/test_startup_workflow.py -q`

Expected: fail because the startup workflow does not exist.

- [ ] **Step 3: Implement guarded transitions, copy mapping, and fresh retries**

The coordinator rejects skipped/invalid transitions, maps connector exceptions to `DEVICE_NOT_FOUND`/`DEVICE_BUSY`, maps service reasons to public states, exposes collection progress from monotonic elapsed time, and accepts a safe exit callback without ever setting `can_enter_workbench`.

- [ ] **Step 4: Run workflow and RAY-113 regression tests**

Run: `./scripts/local-env.sh python -m pytest tests/startup_validation -q`

Expected: all startup domain tests pass.

- [ ] **Step 5: Commit the RAY-114 state slice**

```bash
git add client/startup_validation/workflow.py tests/startup_validation/test_startup_workflow.py
git commit -m "Add mandatory startup validation workflow"
```

### Task 5: RAY-114 Steady Health startup page and launch gate

**Files:**
- Create: `client/app/startup_validation.py`
- Modify: `client/app/design_system.py`
- Modify: `client/app/packaged_entry.py`
- Modify: `main.py`
- Test: `client/tests/test_ray_114_startup_ui.py`
- Test: `client/tests/test_ray_114_packaged_gate.py`

**Interfaces:**
- Consumes: `StartupPresentation` updates and a workbench factory.
- Produces: `StartupValidationWindow.present(model)`, a background runner that never blocks the Qt thread, and `run_validated_application(...)` that shows the workbench only after `PASSED`.

- [ ] **Step 1: Write failing UI and entry-gate tests**

```python
def test_connecting_is_indeterminate_and_collecting_is_monotonic_determinate(qtbot):
    window.present(connecting())
    assert window.progress.maximum() == 0
    window.present(collecting(elapsed_ns=2_500_000_000))
    assert window.progress.value() == 50
    assert window.countdown.text() == "3"

def test_failure_has_plain_copy_one_primary_recovery_and_safe_exit(qtbot):
    window.present(device_busy())
    assert primary_buttons(window) == ["关闭占用程序后重试"]
    assert window.findChild(QPushButton, "EXIT_APPLICATION") is not None
    assert_no_internal_terms(window, {"串口", "阈值", "CheckSum", "堆栈", "坏点"})

def test_workbench_factory_is_not_called_until_passed():
    gate.start()
    assert factory.calls == 0
    gate.on_completed(passed_run())
    assert factory.calls == 1
```

- [ ] **Step 2: Run UI/gate tests and verify RED**

Run: `QT_QPA_PLATFORM=offscreen ./scripts/local-env.sh python -m pytest client/tests/test_ray_114_startup_ui.py client/tests/test_ray_114_packaged_gate.py -q`

Expected: fail because the startup window and launch gate do not exist.

- [ ] **Step 3: Implement the startup-only window and packaged composition**

The page reuses the 64px white header, TechFlex logo, `#F8FAFC` canvas, 720px reading width, 12px card radius, 56px primary button, existing success/warning SVGs, and shared QSS. Connecting uses `QProgressBar.setRange(0, 0)`; baseline collection uses `0..100`; countdown is derived from remaining monotonic nanoseconds. A worker thread performs blocking reads; Qt receives only immutable presentation snapshots. The normal top navigation is never created until the workbench opens.

- [ ] **Step 4: Run UI, existing UI, and entry tests**

Run: `QT_QPA_PLATFORM=offscreen ./scripts/local-env.sh python -m pytest client/tests/test_ray_114_startup_ui.py client/tests/test_ray_114_packaged_gate.py client/tests/test_ui_design_system.py client/tests/test_ray_101_qt_shell.py -q`

Expected: all selected tests pass.

- [ ] **Step 5: Commit the RAY-114 UI slice**

```bash
git add client/app/startup_validation.py client/app/design_system.py client/app/packaged_entry.py main.py client/tests/test_ray_114_startup_ui.py client/tests/test_ray_114_packaged_gate.py
git commit -m "Gate the workbench behind startup validation"
```

### Task 6: RAY-114 repeatable UI capture and evidence

**Files:**
- Create: `scripts/capture_startup_validation.py`
- Create: `docs/evidence/linear/RAY-114/README.md`
- Create: `docs/evidence/linear/RAY-114/issue-snapshot.json`
- Create: `docs/evidence/linear/RAY-114/connecting-1440x900.png`
- Create: `docs/evidence/linear/RAY-114/collecting-1440x900.png`
- Create: `docs/evidence/linear/RAY-114/passed-1440x900.png`
- Create: `docs/evidence/linear/RAY-114/failure-1440x900.png`
- Create: `docs/evidence/linear/RAY-114/long-copy-1280x720.png`

**Interfaces:**
- Consumes: deterministic `StartupPresentation` fixtures only; no serial/database/network adapters.
- Produces: stable screenshots for connection, countdown, pass, failure, minimum viewport, focus, and long-copy review.

- [ ] **Step 1: Write and run the deterministic capture script**

Run: `QT_QPA_PLATFORM=offscreen ./scripts/local-env.sh python scripts/capture_startup_validation.py --output docs/evidence/linear/RAY-114`

Expected: five named PNG files at exact 1440x900 or 1280x720 dimensions.

- [ ] **Step 2: Inspect every capture**

Verify visual consistency with `design-qa.md` and `docs/ui-desgin`: header, type hierarchy, whitespace, progress semantics, status icon+text+color, one primary action, keyboard focus, wrapped long copy, and absence of technical details.

- [ ] **Step 3: Run RAY-114 verification and write evidence**

Run: `QT_QPA_PLATFORM=offscreen ./scripts/local-env.sh python -m pytest client/tests/test_ray_114_*.py client/tests/test_ui_design_system.py client/tests/test_ray_101_qt_shell.py -q --junitxml=docs/evidence/linear/RAY-114/pytest-results.xml`

Expected: exit 0. Evidence marks real Windows scaling, screen reader, target keyboard, hardware timing, and operator usability as unverified.

- [ ] **Step 4: Commit, update Linear, and re-read**

```bash
git add scripts/capture_startup_validation.py docs/evidence/linear/RAY-114
git commit -m "Document RAY-114 startup UI evidence"
```

Set RAY-114 to `In Review`, comment with commit/evidence/tests/unverified items, and re-read before starting RAY-115.

### Task 7: RAY-115 auditable persistence and safe retry queue

**Files:**
- Modify: `client/spool/state_store.py`
- Create: `client/startup_validation/persistence.py`
- Test: `tests/spool/test_validation_runs.py`
- Test: `tests/startup_validation/test_persistence.py`

**Interfaces:**
- Consumes: completed `DeviceValidationRun.safe_summary()` and state transitions.
- Produces: additive SQLite schema v2 tables `device_validation_runs` and `telemetry_events`, plus `ValidationPersistenceAdapter.record(run)`.

- [ ] **Step 1: Write failing migration, audit, privacy, and offline tests**

```python
def test_validation_run_and_pending_telemetry_commit_atomically():
    adapter.record(run)
    assert store.validation_run(run.validation_run_id).outcome == "PASS"
    assert store.telemetry_state_for(run.validation_run_id) == "PENDING"

def test_safe_summary_never_persists_identity_raw_frames_thresholds_or_stack():
    adapter.record(run)
    db = database_path.read_bytes()
    for forbidden in (b"subject", b"patient", b"raw_frame", b"traceback", b"threshold"):
        assert forbidden not in db

def test_offline_telemetry_failure_does_not_change_local_pass_or_retry():
    assert coordinator_with_failing_uploader().run().outcome is ValidationOutcome.PASS
```

- [ ] **Step 2: Run persistence tests and verify RED**

Run: `./scripts/local-env.sh python -m pytest tests/spool/test_validation_runs.py tests/startup_validation/test_persistence.py -q`

Expected: fail because schema v2 and the adapter are absent.

- [ ] **Step 3: Add the migration and adapter without changing segment semantics**

Schema v2 stores run IDs, previous run ID, terminal/device opaque references, app/protocol/data/rule/schema versions, attempt, outcome, stable reason/error code, wall/monotonic boundaries, safe statistics JSON, transition JSON, diagnostic ID, and timestamps. `telemetry_events` stores a safe event envelope and retry state independent of segment upload. The adapter performs one transaction; no raw NumPy bytes, identity, customer record, threshold values, stack, or arbitrary path is accepted.

- [ ] **Step 4: Run persistence plus spool regression tests**

Run: `./scripts/local-env.sh python -m pytest tests/spool tests/startup_validation/test_persistence.py -q`

Expected: all spool and validation persistence tests pass.

- [ ] **Step 5: Commit the RAY-115 persistence slice**

```bash
git add client/spool/state_store.py client/startup_validation/persistence.py tests/spool/test_validation_runs.py tests/startup_validation/test_persistence.py
git commit -m "Persist safe startup validation evidence"
```

### Task 8: RAY-115 recovery policy and fault-injection closure

**Files:**
- Modify: `client/startup_validation/workflow.py`
- Modify: `client/app/startup_validation.py`
- Test: `tests/startup_validation/test_failure_recovery.py`
- Test: `client/tests/test_ray_115_public_failures.py`

**Interfaces:**
- Consumes: previous run outcome/reason and `ValidationThresholds.service_required_after`.
- Produces: repeat-failure escalation, stable diagnostic codes, guaranteed new-run retries, and customer-safe recovery presentation.

- [ ] **Step 1: Write failing fault-injection and leakage tests**

```python
@pytest.mark.parametrize("case", ["no-device", "busy", "load", "disconnect", "stuck", "saturated", "noise", "internal"])
def test_fault_has_stable_code_one_action_and_no_stale_success(case):
    first = run_fault(case)
    second = retry_with_pass(case)
    assert first.validation_run_id != second.validation_run_id
    assert not first.can_enter_workbench
    assert second.outcome is ValidationOutcome.PASS
    assert public_primary_action_count(first.presentation) == 1
    assert_no_internal_details(first.presentation)

def test_repeated_signal_failure_escalates_by_versioned_threshold():
    runs = repeat_signal_failure(3)
    assert runs[-1].outcome is ValidationOutcome.SERVICE_REQUIRED
```

- [ ] **Step 2: Run fault tests and verify RED**

Run: `QT_QPA_PLATFORM=offscreen ./scripts/local-env.sh python -m pytest tests/startup_validation/test_failure_recovery.py client/tests/test_ray_115_public_failures.py -q`

Expected: fail until escalation and full recovery mapping are connected.

- [ ] **Step 3: Implement escalation and recovery**

Every action reconstructs connector/service inputs, clears progress, references the previous run, and starts at `BOOTSTRAPPING`. Signal-invalid attempts escalate to `SERVICE_REQUIRED` at the versioned attempt threshold; device/load/stream failures remain recoverable. Unexpected exceptions become `INTERNAL_ERROR` with stable `E-INI-006` public code and a unique opaque diagnostic ID in internal evidence.

- [ ] **Step 4: Run the full fault and UI matrix**

Run: `QT_QPA_PLATFORM=offscreen ./scripts/local-env.sh python -m pytest tests/startup_validation client/tests/test_ray_114_*.py client/tests/test_ray_115_*.py tests/spool -q`

Expected: all selected tests pass and no forbidden technical term appears in public widget text.

- [ ] **Step 5: Commit the RAY-115 recovery slice**

```bash
git add client/startup_validation/workflow.py client/app/startup_validation.py tests/startup_validation/test_failure_recovery.py client/tests/test_ray_115_public_failures.py
git commit -m "Add startup validation failure recovery"
```

### Task 9: Final evidence, regression, commits, and Linear review states

**Files:**
- Create: `docs/evidence/linear/RAY-115/README.md`
- Create: `docs/evidence/linear/RAY-115/issue-snapshot.json`
- Create: `docs/evidence/linear/RAY-115/pytest-results.xml`
- Create: `docs/evidence/linear/RAY-115/public-failure-states.png`
- Modify: `docs/evidence/linear/RAY-113/README.md`
- Modify: `docs/evidence/linear/RAY-114/README.md`

**Interfaces:**
- Consumes: all RAY-113/114/115 commits, current dirty-worktree diff, captures, and fresh test output.
- Produces: final review evidence and confirmed Linear comments/statuses.

- [ ] **Step 1: Capture final failure matrix and inspect it**

Run: `QT_QPA_PLATFORM=offscreen ./scripts/local-env.sh python scripts/capture_startup_validation.py --output docs/evidence/linear/RAY-115 --failure-matrix`

Expected: a deterministic customer-safe failure-state image; manually confirm one primary recovery action, safe exit, wrapped copy, stable code, and no internal detail.

- [ ] **Step 2: Run full automated verification**

Run: `QT_QPA_PLATFORM=offscreen ./scripts/local-env.sh python -m pytest -q --junitxml=docs/evidence/linear/RAY-115/pytest-results.xml`

Run: `./scripts/local-env.sh python -m compileall -q client tests scripts`

Run: `! rg -n "(坏点|CheckSum|checksum|阈值|traceback|stack trace|raw curve|串口错误)" client/app/startup_validation.py`

Run: `git diff --check`

Expected: pytest/compile/diff checks exit 0 and the public-copy scan returns no matches.

- [ ] **Step 3: Audit scope and concurrent changes before staging**

Run: `git status --short && git diff --stat && git diff --name-only`

Only stage files explicitly listed in this plan. Re-read overlapping diffs in `design_system.py`, `packaged_entry.py`, `main.py`, and `state_store.py`; exclude all unrelated UI, spool, evidence, and workspace files.

- [ ] **Step 4: Write final evidence and commit**

The RAY-115 README includes exact commands/results, run/log schema versions, failure matrix, privacy scan, screenshots, commit SHAs, and explicit unverified boundaries: real DO-P4864 multi-cold-start/load/unplug/reconnect, Windows high-DPI/keyboard/screen-reader, operator usability, and production telemetry upload/backend diagnosis.

```bash
git add docs/evidence/linear/RAY-113 docs/evidence/linear/RAY-114 docs/evidence/linear/RAY-115
git commit -m "Complete startup validation evidence"
```

- [ ] **Step 5: Update Linear and re-read all three issues**

Set RAY-115 to `In Review`; comment on RAY-113, RAY-114, RAY-115, and RAY-101 with final commit SHA(s), evidence paths, automated results, and unverified items. Re-read all statuses/comments and confirm all three are `In Review`, not `Done`.

## Self-Review

- Spec coverage: collector timing, real parser path, validation rules, mandatory gate, progress semantics, retries, recovery, privacy, telemetry queue, UI consistency, captures, evidence, and review-state boundaries each map to a task.
- Placeholder scan: no `TBD`, `TODO`, “similar to”, or unbounded “handle errors” step remains.
- Type consistency: `DeviceValidationRun`, `ValidationThresholds`, `StartupPresentation`, and coordinator/service signatures are defined before consumers; retries pass only IDs and immutable summaries, never frame windows.
- Dirty-worktree safety: all overlapping files are additive integration points and get an explicit pre-stage audit; no plan step stages broad directories outside this feature.
