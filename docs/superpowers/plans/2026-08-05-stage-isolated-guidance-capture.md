# Stage-Isolated Guidance and Hardware Capture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the continuous four-stage hardware run with four operator-started 20-second recording windows, each preceded by its own two-image guidance page, while keeping one logical screening session and excluding all preparation frames from storage and analysis.

**Architecture:** Keep the physical connection/read loop alive while a thread-safe stage gate decides whether each decoded frame is display-only or belongs to the current durable stage attempt. Seal a successful stage attempt, append only its verified frames to the final session stager, preserve real non-contiguous stage timing for analysis, and return the workflow to guidance after every non-final stage. The Qt bridge polls stage progress and transports worker completion/failure back to the UI thread.

**Tech Stack:** Python 3.12, PySide6, NumPy, encrypted `ImmutableSegmentWriter`/`ValidSessionStager`, pytest/pytest-qt, `uv` through `./scripts/local-env.sh`.

## Global Constraints

- Run every Python command through `./scripts/local-env.sh`; do not create a repository-local `.venv`.
- The device stays connected across normal stage transitions; preparation frames are display-only and must never enter the final stager or analysis.
- Every stage starts only from the operator's “开始本段” action and records exactly its configured 20 seconds; no stable-standing, contact, valid-area, countdown, or auto-start gate may block the operator.
- Four stages remain ordered: `BILATERAL_EYES_OPEN`, `BILATERAL_EYES_CLOSED`, `SEMI_TANDEM_LEFT_FORWARD`, `SEMI_TANDEM_RIGHT_FORWARD`.
- The final BASIC report remains non-diagnostic and is unavailable until all four stage windows, hardware quality, encrypted commit, and operator attestations succeed.
- Runtime assets must live under `client/app/assets/position-guidance/`; the packaged app must not depend on `/Users/ruiguo/Downloads/ref graph/`.
- Preserve the existing unrelated modifications in `client/tests/test_live_hardware_demo_script.py`, `scripts/run_dop4864_live_hardware_demo.py`, and `.planning/2026-08-04-asset-serial-activation/`.

---

## File Structure

- `client/device/stage_windows.py`: thread-safe active-window gate plus immutable captured-stage timing records.
- `client/spool/stage_attempt.py`: encrypted, discardable spool for one stage attempt before it is merged into the final session stager.
- `client/app/live_physical_workflow.py`: owns the persistent connection, read loop, stage attempts, final quality gate/commit, and real stage timing handed to analysis.
- `client/app/live_hardware_acquisition.py`: Qt-thread bridge that opens one stage at a time and reports gate progress without automatically starting the next stage.
- `client/app/live_hardware_demo.py`: builds operator-attested protocol context from captured non-contiguous stage windows.
- `client/workflow/coordinator.py`: always returns non-final completion to guidance and supports retrying only the current failed stage.
- `client/app/controller.py`: routes stage-complete, retryable-stage-failure, and final-capture events.
- `client/app/position_guide.py`: responsive two-image stage guidance widget.
- `client/app/qt_shell.py`: stage-specific guidance binding and operator copy.
- `client/app/live_institution_runtime.py`: composition of the stage capture worker, Qt bridge, processor, and callbacks.
- `client/app/assets/position-guidance/`: eight supplied runtime images with normalized names.

---

### Task 1: Captured Stage Timing Contract

**Files:**
- Create: `client/device/stage_windows.py`
- Modify: `client/app/live_hardware_demo.py:52-126`
- Modify: `client/app/live_physical_workflow.py:142-196`
- Test: `client/tests/test_stage_windows.py`
- Test: `client/tests/test_live_hardware_demo.py`
- Test: `client/tests/test_live_physical_workflow.py`

**Interfaces:**
- Produces: `CapturedStageWindow(stage_id: str, start_s: float, end_s: float, frame_count: int)`.
- Produces: `validate_captured_stage_windows(windows, expected_stage_ids, minimum_duration_s) -> tuple[CapturedStageWindow, ...]`.
- Extends: `build_operator_attested_protocol(..., captured_windows: tuple[CapturedStageWindow, ...] | None = None)`.
- Extends: `LivePhysicalProcessor.record_attestations(session_id, completed, captured_windows=...)`.

- [ ] **Step 1: Write failing timing-contract tests**

```python
def test_captured_windows_allow_preparation_gaps_but_require_protocol_order():
    windows = (
        CapturedStageWindow("BILATERAL_EYES_OPEN", 0.0, 20.0, 600),
        CapturedStageWindow("BILATERAL_EYES_CLOSED", 34.5, 54.5, 601),
        CapturedStageWindow("SEMI_TANDEM_LEFT_FORWARD", 70.0, 90.0, 599),
        CapturedStageWindow("SEMI_TANDEM_RIGHT_FORWARD", 105.0, 125.0, 602),
    )
    assert validate_captured_stage_windows(
        windows,
        expected_stage_ids=tuple(stage.stage_id for stage in default_standard_protocol().stages),
        minimum_duration_s=20.0,
    ) == windows


def test_operator_context_uses_real_non_contiguous_stage_boundaries():
    context = build_operator_attested_protocol(
        session_id="session-1",
        stage_seconds=20.0,
        attestations=_completed_attestations(),
        captured_windows=_captured_windows_with_gaps(),
    )
    assert [(stage.start_s, stage.end_s) for stage in context.stages] == [
        (0.0, 20.0), (34.5, 54.5), (70.0, 90.0), (105.0, 125.0)
    ]
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
./scripts/local-env.sh python -m pytest \
  client/tests/test_stage_windows.py \
  client/tests/test_live_hardware_demo.py \
  client/tests/test_live_physical_workflow.py -q
```

Expected: collection/import failure because `CapturedStageWindow` and the captured-window argument do not exist.

- [ ] **Step 3: Implement the immutable validation contract**

```python
@dataclass(frozen=True, slots=True)
class CapturedStageWindow:
    stage_id: str
    start_s: float
    end_s: float
    frame_count: int

    def __post_init__(self) -> None:
        if not self.stage_id or self.start_s < 0 or self.end_s <= self.start_s:
            raise ValueError("captured stage timing is invalid")
        if self.frame_count <= 0:
            raise ValueError("captured stage must contain frames")
```

Validation must reject missing, duplicate, reordered, overlapping, or shorter-than-20-second windows, while permitting any positive preparation gap. `build_operator_attested_protocol` must copy these start/end values into `StageWindow`; when the optional argument is absent, retain the existing contiguous-plan behavior for replay/debug callers.

- [ ] **Step 4: Store captured windows with attestations in the live processor**

Use one per-session record:

```python
@dataclass(frozen=True, slots=True)
class LiveAnalysisInputs:
    completed: tuple[bool, ...]
    captured_windows: tuple[CapturedStageWindow, ...]
```

`process()` must return `RETRY_REQUIRED` unless both four attestations and four validated windows are present, then call `build_operator_attested_protocol(..., captured_windows=inputs.captured_windows)`.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run the Step 2 command. Expected: all selected tests pass.

- [ ] **Step 6: Commit Task 1**

```bash
git add client/device/stage_windows.py client/app/live_hardware_demo.py \
  client/app/live_physical_workflow.py client/tests/test_stage_windows.py \
  client/tests/test_live_hardware_demo.py client/tests/test_live_physical_workflow.py
git commit -m "Add real stage timing contract"
```

---

### Task 2: Durable Retryable Stage Attempts

**Files:**
- Create: `client/spool/stage_attempt.py`
- Test: `client/tests/test_stage_attempt.py`
- Modify: `client/spool/session_commit.py:105-178`

**Interfaces:**
- Consumes: `RawFrame`, `ImmutableSegmentWriter`, `read_segment`, `KeyProvider`, `ValidSessionStager.append`.
- Produces: `StageAttemptSpool(root, session_id, stage_id, key_provider, versions)`.
- Produces: `append(frame)`, `seal() -> tuple[RawFrame, ...]`, `discard(reason) -> None`.
- Produces: `ValidSessionStager.append_verified_stage(stage_id, frames, window) -> None` and `stage_windows` property.

- [ ] **Step 1: Write failing stage-attempt tests**

```python
def test_failed_stage_attempt_is_deleted_without_touching_previous_stage(tmp_path):
    first = _attempt(tmp_path, "stage-1")
    first.append(_frame(0))
    assert len(first.seal()) == 1
    second = _attempt(tmp_path, "stage-2")
    second.append(_frame(1))
    second.discard(reason="operator retry")
    assert not second.staging_directory.exists()
    assert first.staging_directory.exists()


def test_final_stager_accepts_only_sealed_stage_frames_in_order(tmp_path):
    stager = _valid_session_stager(tmp_path)
    stager.append_verified_stage("stage-1", (_frame(0),), _window("stage-1", 0, 20))
    with pytest.raises(ValueError, match="stage order"):
        stager.append_verified_stage("stage-3", (_frame(2),), _window("stage-3", 40, 60))
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
./scripts/local-env.sh python -m pytest client/tests/test_stage_attempt.py -q
```

Expected: import or attribute failure for `StageAttemptSpool`/`append_verified_stage`.

- [ ] **Step 3: Implement the discardable encrypted attempt spool**

Each attempt must use a unique directory below:

```text
<spool-root>/.stage-attempts/<session-id>/<stage-id>/<attempt-uuid>/
```

`seal()` closes the immutable writer, verifies/decrypts its segments through `read_segment`, returns ordered frames, and leaves the attempt available until merge succeeds. `discard()` removes only the current attempt directory and fsyncs its parent. No attempt calls `StateStore.commit_valid_session`.

- [ ] **Step 4: Add ordered stage append to the final stager**

`append_verified_stage()` must validate stage identity/order, append every verified frame, retain the immutable `CapturedStageWindow`, and reject a duplicate stage. Add the windows to derived `processing_metadata` and frozen versions as `stage_window_policy=operator-started-stage-window/1`; do not put absolute subject identifiers in metadata.

- [ ] **Step 5: Run stage-attempt and existing spool regression tests**

```bash
./scripts/local-env.sh python -m pytest \
  client/tests/test_stage_attempt.py \
  client/tests/test_session_commit.py \
  client/tests/test_segments.py -q
```

Expected: all selected tests pass.

- [ ] **Step 6: Commit Task 2**

```bash
git add client/spool/stage_attempt.py client/spool/session_commit.py \
  client/tests/test_stage_attempt.py
git commit -m "Add retryable encrypted stage attempts"
```

---

### Task 3: Persistent Device Loop with Manual Recording Gate

**Files:**
- Modify: `client/device/stage_windows.py`
- Modify: `client/app/live_physical_workflow.py:73-140`
- Modify: `client/app/live_hardware_acquisition.py:1-143`
- Test: `client/tests/test_live_stage_capture.py`
- Rewrite: `client/tests/test_qt_live_hardware_acquisition.py`

**Interfaces:**
- Produces: `StageRecordingGate.open_stage(stage_id, duration_seconds)`, `observe(frame)`, `cancel_current_stage()`, `snapshot()`.
- Produces: `StageGateSnapshot(stage_id, elapsed_seconds, completed_windows, stage_complete, session_complete, cancelled)`.
- Changes: `LivePhysicalCapture.capture(session_id, gate) -> HardwareSessionResult` with `result.stage_windows`.
- Changes: `QtLiveHardwareAcquisition(capture_session)` where `capture_session(session_id, gate)` runs once, but `start_stage(session_id, stage)` opens every manual window.

- [ ] **Step 1: Write failing gate tests**

```python
def test_gate_discards_preparation_frames_and_closes_each_manual_window():
    gate = StageRecordingGate(expected_stage_ids=("one", "two"))
    assert not gate.observe(_frame_at(1.0)).record
    gate.open_stage("one", duration_seconds=20)
    assert gate.observe(_frame_at(10.0)).record
    end = gate.observe(_frame_at(30.0))
    assert end.record and end.stage_complete and not end.session_complete
    assert not gate.observe(_frame_at(35.0)).record
    gate.open_stage("two", duration_seconds=20)
    final = gate.observe(_frame_at(60.0))
    final = gate.observe(_frame_at(80.0))
    assert final.stage_complete and final.session_complete
```

Also assert that a second `open_stage()` while active, an out-of-order stage, and a session-id change fail closed.

- [ ] **Step 2: Write failing live-capture tests with a controlled transport**

The controlled stream must contain three classes of frames: preparation frames before stage 1, 20 seconds of stage 1, preparation frames with a distinctive matrix value, then stage 2. Assert the final stager never receives the distinctive preparation value and that `connect_startup()` is called once during a successful session.

- [ ] **Step 3: Run gate/capture tests and verify RED**

```bash
./scripts/local-env.sh python -m pytest \
  client/tests/test_stage_windows.py \
  client/tests/test_live_stage_capture.py \
  client/tests/test_qt_live_hardware_acquisition.py -q
```

Expected: failures because the recording gate and staged capture API do not exist.

- [ ] **Step 4: Implement the persistent read loop**

The loop must follow this order for every decoded frame:

```python
decision = gate.observe(frame)
self._latest_frames.publish(frame)       # every valid frame may update UI
if not decision.record:
    reset_stage_continuity_state()
    continue                             # never touch a durable sink
attempt.append(frame)                    # only active-window frames
if decision.stage_complete:
    verified = attempt.seal()
    final_stager.append_verified_stage(decision.stage_id, verified, decision.window)
    attempt.discard(reason="merged into final session")
if decision.session_complete:
    break
```

Within each active window, preserve the existing five-second valid-signal continuity and parser-integrity handling. Reset previous-frame/pending-integrity state whenever the gate is inactive so a long preparation gap is not reconstructed or treated as a scored-data outage. On retryable stage failure, discard only the active attempt, retain completed stages/final stager, close the broken transport, and permit a new worker connection for the same session/current stage. On final success, run `DoP4864HardwareQualityGate` over only merged frames, stage the physical observation plus captured-window metadata, and call `commit_valid()` once.

- [ ] **Step 5: Replace Qt auto-advance timing with gate snapshots**

Remove `continuous_stage_capture`, `_stage_started_at` auto-rollover, and the implicit next-stage clock. `start_stage()` must call `gate.open_stage(stage.stage_id, stage.duration_seconds)` every time. The 100 ms Qt timer polls `gate.snapshot()` and calls `on_progress(elapsed_seconds)`; it emits the terminal duration once when the worker reports `stage_complete`, which lets the coordinator transition pages. Final capture completion is delivered only after both the fourth UI stage and the committed worker result exist.

- [ ] **Step 6: Run focused tests and verify GREEN**

Run the Step 3 command. Expected: all selected tests pass, including preparation-frame exclusion and one physical connection.

- [ ] **Step 7: Commit Task 3**

```bash
git add client/device/stage_windows.py client/app/live_physical_workflow.py \
  client/app/live_hardware_acquisition.py client/tests/test_live_stage_capture.py \
  client/tests/test_qt_live_hardware_acquisition.py
git commit -m "Capture four operator-started hardware stages"
```

---

### Task 4: Workflow Stage Boundaries and Current-Stage Retry

**Files:**
- Modify: `client/workflow/coordinator.py:201-279,281-342,421-461`
- Modify: `client/workflow/state_machine.py:20-62`
- Modify: `client/app/controller.py:236-280`
- Replace: `client/tests/test_continuous_live_stage_workflow.py`
- Modify: `client/tests/test_v1_staged_coordinator.py`
- Modify: `client/tests/test_ray_101_controller.py`

**Interfaces:**
- Produces: `ScreeningCoordinator.handle_stage_capture_failure(technical_detail: str) -> None`.
- Produces: `SessionStateMachine.retry_current_stage()` transition from a retryable stage error to `POSITION_GUIDANCE` without resetting `stage_index` or `session_id`.
- Changes: final capture callback forwards `result.stage_windows` into `record_attestations`.

- [ ] **Step 1: Replace the continuous-flow test with the required page sequence**

```python
def test_each_live_stage_requires_guidance_and_a_new_operator_start():
    coordinator, acquisition = _ready_live_coordinator()
    for index, expected_stage in enumerate(EXPECTED_STAGE_IDS):
        assert coordinator.state.step is ScreeningStep.POSITION_GUIDANCE
        assert coordinator.state.stage_index == index + 1
        assert coordinator.start_acquisition()
        assert acquisition.started[-1] == ("physical-session-1", expected_stage)
        coordinator.observe_acquisition_elapsed(elapsed_seconds=20)
    assert coordinator.state.step is ScreeningStep.FINALIZING
    assert len(acquisition.started) == 4
```

- [ ] **Step 2: Add the retry-current-stage test**

```python
def test_retryable_second_stage_failure_preserves_first_stage_and_session():
    coordinator, acquisition = _coordinator_after_first_stage()
    session_id = coordinator.state.session_id
    assert coordinator.start_acquisition()
    coordinator.handle_stage_capture_failure(technical_detail="serial disconnected")
    assert coordinator.state.step is ScreeningStep.POSITION_GUIDANCE
    assert coordinator.state.stage_index == 2
    assert coordinator.state.session_id == session_id
    assert coordinator.start_acquisition()
    assert acquisition.started[-1][1] == "BILATERAL_EYES_CLOSED"
```

- [ ] **Step 3: Run focused workflow tests and verify RED**

```bash
./scripts/local-env.sh python -m pytest \
  client/tests/test_continuous_live_stage_workflow.py \
  client/tests/test_v1_staged_coordinator.py \
  client/tests/test_ray_101_controller.py -q
```

Expected: the old continuous acquisition remains on `ACQUIRING`, and the retry API is absent.

- [ ] **Step 4: Make every non-final completion return to guidance**

Delete the `continuous_stage_capture` branch. After `mark_stage_complete`, increment `_stage_index`, clear remaining time, transition to `POSITION_GUIDANCE`, call `set_stage()` and `reset()`, and leave the session id intact. The final stage alone transitions to `FINALIZING` and calls acquisition `finish()`.

- [ ] **Step 5: Implement retry-current-stage without reintroducing a standing gate**

The failure handler must record telemetry, ask acquisition to discard/cancel only the current attempt, preserve prior stage completions, set a non-blocking notice such as `本段采集中断，请重新连接设备并重测本段`, and transition back to the same stage's guidance. It must not call `sessions.mark_incomplete()` unless the acquisition reports a non-recoverable final-session failure.

Change the obsolete start error copy from `请站到压力垫中央并保持站稳` to `请由操作员确认站位和安全后开始本段`; the default protocol still keeps `manual_start_allowed=True` without contact/stability prerequisites.

- [ ] **Step 6: Forward captured windows through controller finalization**

On a committed result, call:

```python
record_attestations(
    session_id,
    completed,
    captured_windows=tuple(result.stage_windows),
)
```

Stage-worker errors use `handle_stage_capture_failure`; final quality/commit errors continue to use the existing fail-closed whole-session path.

- [ ] **Step 7: Run focused workflow tests and verify GREEN**

Run the Step 3 command. Expected: all selected tests pass.

- [ ] **Step 8: Commit Task 4**

```bash
git add client/workflow/coordinator.py client/workflow/state_machine.py \
  client/app/controller.py client/tests/test_continuous_live_stage_workflow.py \
  client/tests/test_v1_staged_coordinator.py client/tests/test_ray_101_controller.py
git commit -m "Require manual start for every screening stage"
```

---

### Task 5: Four Two-Image Guidance Pages

**Files:**
- Create: `client/app/assets/position-guidance/stage-1-body.png`
- Create: `client/app/assets/position-guidance/stage-1-feet.png`
- Create: `client/app/assets/position-guidance/stage-2-body.png`
- Create: `client/app/assets/position-guidance/stage-2-feet.png`
- Create: `client/app/assets/position-guidance/stage-3-body.png`
- Create: `client/app/assets/position-guidance/stage-3-feet.png`
- Create: `client/app/assets/position-guidance/stage-4-body.png`
- Create: `client/app/assets/position-guidance/stage-4-feet.jpg`
- Modify: `client/app/position_guide.py:1-55`
- Modify: `client/app/qt_shell.py:560-587,1472-1537`
- Modify: `client/tests/test_ui_design_system.py:45-55`
- Modify: `client/tests/test_ray_91_qt.py:14-48`
- Test: `client/tests/test_position_guidance_assets.py`

**Interfaces:**
- Produces: `StageGuidanceWidget.set_stage(stage_index: int) -> None`.
- Produces: child labels `stageBodyGuide` and `stageFeetGuide`, both with scaled contents and preserved aspect ratio.
- Consumes: `WorkflowState.stage_index` values 1 through 4.

- [ ] **Step 1: Copy and normalize the approved assets**

Copy without redrawing or content changes:

```bash
mkdir -p client/app/assets/position-guidance
cp '/Users/ruiguo/Downloads/ref graph/1-1.png' client/app/assets/position-guidance/stage-1-body.png
cp '/Users/ruiguo/Downloads/ref graph/1-2.png' client/app/assets/position-guidance/stage-1-feet.png
cp '/Users/ruiguo/Downloads/ref graph/2-1.png' client/app/assets/position-guidance/stage-2-body.png
cp '/Users/ruiguo/Downloads/ref graph/2-2.png' client/app/assets/position-guidance/stage-2-feet.png
cp '/Users/ruiguo/Downloads/ref graph/3-1.png' client/app/assets/position-guidance/stage-3-body.png
cp '/Users/ruiguo/Downloads/ref graph/3-2.png' client/app/assets/position-guidance/stage-3-feet.png
cp '/Users/ruiguo/Downloads/ref graph/4-1 .png' client/app/assets/position-guidance/stage-4-body.png
cp '/Users/ruiguo/Downloads/ref graph/4-2.jpg' client/app/assets/position-guidance/stage-4-feet.jpg
```

- [ ] **Step 2: Write failing asset and Qt binding tests**

```python
@pytest.mark.parametrize("stage_index", (1, 2, 3, 4))
def test_stage_guidance_loads_the_numbered_body_and_feet_images(qtbot, stage_index):
    widget = StageGuidanceWidget()
    qtbot.addWidget(widget)
    widget.set_stage(stage_index)
    assert not widget.findChild(QLabel, "stageBodyGuide").pixmap().isNull()
    assert not widget.findChild(QLabel, "stageFeetGuide").pixmap().isNull()
    assert widget.property("guidanceStage") == stage_index
```

The Qt-shell test must present stage indexes 1–4 and assert the widget property changes in the same order while the start button remains enabled for a `READY` guidance state.

- [ ] **Step 3: Run UI tests and verify RED**

```bash
QT_QPA_PLATFORM=offscreen ./scripts/local-env.sh python -m pytest \
  client/tests/test_position_guidance_assets.py \
  client/tests/test_ui_design_system.py \
  client/tests/test_ray_91_qt.py -q
```

Expected: `StageGuidanceWidget` and its labels do not exist.

- [ ] **Step 4: Implement the responsive guidance widget and stage binding**

Replace the painted generic footprint canvas with a two-label widget. Load assets from:

```python
ASSET_ROOT = Path(__file__).with_name("assets") / "position-guidance"
GUIDANCE_ASSETS = {
    1: ("stage-1-body.png", "stage-1-feet.png"),
    2: ("stage-2-body.png", "stage-2-feet.png"),
    3: ("stage-3-body.png", "stage-3-feet.png"),
    4: ("stage-4-body.png", "stage-4-feet.jpg"),
}
```

Scale with `Qt.AspectRatioMode.KeepAspectRatio` on resize; do not crop eyes, feet, or board edges. In `present_state`, call `set_stage(state.stage_index)` and set title/subtitle from the protocol state. Replace `请等待站位稳定` with `操作员确认站位和安全后，点击开始本段`; hide the numeric countdown when none is required.

- [ ] **Step 5: Run UI tests and visually inspect all four states**

Run the Step 3 command, then render/show each stage at the packaged app's normal window size. Verify both images remain visible, text/button do not overlap, and stage 3/4 foot-order images are not swapped.

- [ ] **Step 6: Commit Task 5**

```bash
git add client/app/assets/position-guidance client/app/position_guide.py \
  client/app/qt_shell.py client/tests/test_position_guidance_assets.py \
  client/tests/test_ui_design_system.py client/tests/test_ray_91_qt.py
git commit -m "Show numbered guidance before every stage"
```

---

### Task 6: Live Runtime Composition, Regression, and Real-Hardware Acceptance

**Files:**
- Modify: `client/app/live_institution_runtime.py:92-162`
- Modify: `client/tests/test_live_institution_runtime.py` (create if absent)
- Modify: `client/tests/test_ray_114_startup_ui.py:205-217`
- Modify: `docs/evidence/linear/<active-issue>/README.md` only after identifying the live Linear acceptance issue and collecting real evidence.

**Interfaces:**
- Consumes: the Task 1–5 stage capture, processor, Qt bridge, and guidance widget contracts.
- Produces: one authenticated live runtime whose resource lifetime includes the physical capture worker and whose final callback supplies captured windows to analysis.

- [ ] **Step 1: Write the failing composition test**

Assert `build_live_institution_runtime()` wires `QtLiveHardwareAcquisition(capture.capture)` with the new two-argument capture callable, forwards all three callbacks (progress, committed completion, retryable stage failure), retains capture/connection resources on the window, and includes all eight images in the packaged assets check.

- [ ] **Step 2: Run composition and package tests and verify RED**

```bash
./scripts/local-env.sh python -m pytest \
  client/tests/test_live_institution_runtime.py \
  client/tests/test_ray_114_startup_ui.py -q
```

Expected: composition still uses the old one-argument continuous capture and package assertions do not cover the new images.

- [ ] **Step 3: Update live composition and resource ownership**

Construct the processor before callback binding, forward `result.stage_windows` on final attestation, and retain `(institution, physical_store, acquisition, capture, baseline)` on `institutionLiveResources`. Do not alter License, login, HardwareLease, CA, or cloud endpoint configuration.

- [ ] **Step 4: Run focused live-flow regression**

```bash
QT_QPA_PLATFORM=offscreen ./scripts/local-env.sh python -m pytest \
  client/tests/test_stage_windows.py \
  client/tests/test_stage_attempt.py \
  client/tests/test_live_stage_capture.py \
  client/tests/test_qt_live_hardware_acquisition.py \
  client/tests/test_continuous_live_stage_workflow.py \
  client/tests/test_v1_staged_coordinator.py \
  client/tests/test_position_guidance_assets.py \
  client/tests/test_live_physical_workflow.py \
  client/tests/test_live_institution_runtime.py \
  client/tests/test_ray_91_qt.py \
  client/tests/test_ui_design_system.py \
  client/tests/test_ray_114_startup_ui.py -q
```

Expected: all selected tests pass.

- [ ] **Step 5: Run the broader client regression suite**

```bash
QT_QPA_PLATFORM=offscreen ./scripts/local-env.sh python -m pytest client/tests -q
```

Expected: no new failures. If the two previously observed staged/replay finalization failures remain, record their exact node ids and verify they are unchanged from the pre-task baseline; do not claim the full suite is green.

- [ ] **Step 6: Commit Task 6 code and tests**

```bash
git add client/app/live_institution_runtime.py \
  client/tests/test_live_institution_runtime.py client/tests/test_ray_114_startup_ui.py
git commit -m "Wire stage-isolated capture into live runtime"
```

- [ ] **Step 7: Launch the authenticated real UI without reactivating the consumed License**

Use the existing authenticated local state and integration trust files:

```bash
FEETFORCEPLATE_API_BASE_URL='https://39.105.216.113:7443' \
FEETFORCEPLATE_CA_BUNDLE="$HOME/Library/Application Support/FeetForcePlate/integration/cloud-ca.pem" \
FEETFORCEPLATE_INTEGRATION_MODE=1 \
FEETFORCEPLATE_LICENSE_KEY_ID='license/1' \
FEETFORCEPLATE_LICENSE_PUBLIC_KEY_FILE="$HOME/Library/Application Support/FeetForcePlate/integration/license-public.key" \
./scripts/local-env.sh python -m client.app.packaged_entry
```

Do not submit the already-consumed activation code again.

- [ ] **Step 8: Perform real operator acceptance**

For each of the four stages, verify in the actual UI:

1. The correct numbered body and feet images appear.
2. Preparation time is unlimited and the app does not wait for “站稳”.
3. Only the operator's click starts the 20-second countdown.
4. Completion returns to the next stage's guidance page rather than automatically continuing.
5. Stage 4 alone proceeds to finalization, attestation, BASIC report, preview, and PDF export.

Capture only sanitized evidence: UI screenshots, stage ids, start/end/duration, frame counts, preparation-frame exclusion counts, commit outcome, and report state. Do not record passwords, activation code, raw pressure matrices, subject details, or report content.

- [ ] **Step 9: Re-read Linear and record evidence without premature closure**

Read the active issue before editing its evidence file. Update `docs/evidence/linear/<ISSUE-ID>/README.md` with the commit SHAs, test commands/results, real-hardware stage timings, and screenshot paths. Keep the issue `In Review` if any real operator, packaging, Windows, cloud upload, or report-export criterion remains unverified.

---

## Plan Self-Review

- Spec coverage: four guidance groups, manual start, preparation-frame exclusion, persistent connection, real stage timing, retry-current-stage, final commit/analysis gate, packaging, and physical UI acceptance all map to Tasks 1–6.
- Placeholder review: every task contains concrete files, interfaces, tests, commands, expected outcomes, and commit scope.
- Type consistency: `CapturedStageWindow` is defined once in Task 1; the gate, stager, capture result, controller callback, processor, and protocol context all consume that same type and the same `stage_id/start_s/end_s/frame_count` fields.
- Scope guard: License/login/lease/cloud behavior and diagnostic-report scope remain unchanged.
