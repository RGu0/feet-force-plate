# UI Live Hardware Full Flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the default Qt institution application execute a real MVP flow from inventory activation through hardware acquisition, local BASIC report preview/export, and truthful pending-sync state.

**Architecture:** Replace the bare packaged `ScreeningWindow` composition with `LiveInstitutionScreeningRuntime`. It composes current access credentials, HardwareLease, one encrypted DO-P4864 capture spanning the existing four UI stages, physical local analysis, and the existing report UI. A Qt adapter owns the serial worker and returns final state to the GUI thread.

**Tech Stack:** Python 3.11, PySide6, httpx, keyring, SQLite, pyserial, NumPy.

## Global Constraints

- Run every Python command through `./scripts/local-env.sh`; do not create a repository `.venv`.
- Use `aliyun-agentic:7443` only with `integration_mode=1`, explicit CA and pinned License public key; UI says `联调环境`.
- Asset serial is a business identity, never USB serial, port, VID/PID or USB location.
- Credentials, activation codes, private keys, tokens, raw matrices and unredacted reports never enter logs, tests, evidence or code.
- BASIC_READY requires four completed UI stages, valid quality, encrypted commit and valid physical analysis.
- Stop, disconnect, lease/quality/commit failures discard temporary capture and suppress reports.
- Until a real upload acknowledgement exists, result UI says `待同步`, never `已上传`.

## File Structure

- `client/cloud/lease_runtime.py`: acquire, renew and release a server HardwareLease.
- `client/app/institution_store.py`: keyring-backed tenant-local subjects, consents, sessions, reports and read models.
- `client/app/live_hardware_acquisition.py`: serial worker and stager across four UI stages.
- `client/app/live_physical_reporting.py`: valid committed physical session to BASIC report.
- `client/app/live_institution_runtime.py`: packaged Qt composition.
- `client/app/controller.py`, `client/workflow/coordinator.py`, `client/app/qt_shell.py`: finalization and truthful presentation.

### Task 1: HardwareLease lifecycle

**Files:** Create `client/cloud/lease_runtime.py`; modify `client/cloud/runtime.py`; test `client/tests/test_hardware_lease_runtime.py`.

**Consumes:** authenticated access token, stable server `hardware_id` (`FFP-DP4864-xxxxxx`), installation UUID and existing acquire/renew/release lease routes.

**Produces:** `HardwareLeaseLifecycle.acquire()`, `renew_if_due()`, `release(reason)` and immutable `LeaseState`.

- [ ] **Step 1: Write a failing test**

```python
def test_acquire_binds_authenticated_asset_and_installation() -> None:
    state = HardwareLeaseLifecycle(client, runtime, session, now=clock).acquire()
    assert state.status is LeaseStatus.ACTIVE
    assert client.requests[0].hardware_id == session.hardware_id
```

- [ ] **Step 2: Verify RED**

Run `./scripts/local-env.sh python -m pytest client/tests/test_hardware_lease_runtime.py -q`; expect missing `client.cloud.lease_runtime`.

- [ ] **Step 3: Implement the lifecycle**

```python
class HardwareLeaseLifecycle:
    def acquire(self) -> LeaseState: ...
    def renew_if_due(self) -> LeaseStatus: ...
    def release(self, reason: str) -> None: ...
```

Extend `AccessClientPort` with the typed lease methods already exposed by `CloudAccessClient`. `acquire()` binds `session.hardware_id` (the stable FFP asset identity) and `UUID(session.client_installation_id)`; `hardware_asset_id` is the internal server UUID and is not sent by this route. Renewal failure becomes `RECOVERY_REQUIRED` without deleting a current local session. `release()` is idempotent and runs on worker completion, stop and app close.

- [ ] **Step 4: Verify GREEN and commit**

Run `./scripts/local-env.sh python -m pytest client/tests/test_hardware_lease_runtime.py -q`; then commit `client/cloud/lease_runtime.py`, `client/cloud/runtime.py`, and its test as `Add client hardware lease lifecycle`.

### Task 2: Encrypted institution state and lease-aware preflight

**Files:** Create `client/app/institution_store.py`; modify `client/app/preflight.py`; tests `client/tests/test_institution_store.py`, `client/tests/test_live_institution_preflight.py`.

**Consumes:** `KeyringTerminalKeyHandle`, `DualEnvelopeBlobCodec`, `StateStore`, participant/consent workflows and `LeaseState`.

**Produces:** `InstitutionLocalStore` implementing `SessionPort`, report/read-model ports and `build_live_institution_preflight()`.

- [ ] **Step 1: Write failing tests**

```python
def test_institution_store_has_no_replay_schema(tmp_path: Path) -> None:
    store = InstitutionLocalStore.open(tmp_path, terminal_key=memory_keyring)
    assert "replay_" not in store.schema_names()

def test_preflight_rejects_inactive_lease() -> None:
    summary = build_live_institution_preflight(startup_run=passed, store=store, lease=inactive).run_preflight()
    assert summary.failed_ids == ("hardware_lease",)
```

- [ ] **Step 2: Verify RED**

Run `./scripts/local-env.sh python -m pytest client/tests/test_institution_store.py client/tests/test_live_institution_preflight.py -q`; expect imports to fail.

- [ ] **Step 3: Implement encrypted persistence**

```python
class InstitutionLocalStore(SessionPort, PersistedReportPort, UiReadModelPort):
    @classmethod
    def open(cls, root: Path, *, terminal_key: KeyringTerminalKeyHandle) -> "InstitutionLocalStore": ...
    def create_session(self, context: ScreeningParticipantContext, protocol: ProtocolSnapshot) -> str: ...
```

Use tenant-scoped encrypted `institution_*` tables and HMAC lookup indices; never reuse `LocalReplayStore`. Add `hardware_lease` before existing P-05 network/storage/calibration checks.

- [ ] **Step 4: Verify GREEN and commit**

Run `./scripts/local-env.sh python -m pytest client/tests/test_institution_store.py client/tests/test_live_institution_preflight.py -q`; then commit the store, preflight and two tests as `Add encrypted institution screening store`.

### Task 3: Continuous hardware capture driven by existing UI stages

**Files:** Create `client/app/live_hardware_acquisition.py`; modify `client/workflow/ports.py`, `client/workflow/coordinator.py`, `client/app/controller.py`; tests `client/tests/test_live_hardware_acquisition.py`, `client/tests/test_live_stage_finalization.py`.

**Consumes:** serial transport/parser, `ValidSessionStager`, `DoP4864HardwareQualityGate`, latest-frame mailbox and `HardwareLeaseLifecycle`.

**Produces:** `QtLiveHardwareAcquisition.start_stage()`, `stop()`, `finalize_after_last_stage()` and `CaptureFinalized` callback.

- [ ] **Step 1: Write failing tests**

```python
def test_first_stage_opens_one_capture_for_all_stages() -> None:
    acquisition.start_stage("s-1", first_stage)
    acquisition.start_stage("s-1", second_stage)
    assert transport.open_count == 1

def test_last_stage_waits_for_worker_commit() -> None:
    acquisition.finalize_after_last_stage("s-1")
    assert callbacks == []
    worker.finish_valid()
    assert callbacks == [CaptureFinalized.valid("s-1")]
```

- [ ] **Step 2: Verify RED**

Run `./scripts/local-env.sh python -m pytest client/tests/test_live_hardware_acquisition.py client/tests/test_live_stage_finalization.py -q`; expect module missing.

- [ ] **Step 3: Implement one-worker capture**

```python
class QtLiveHardwareAcquisition(QObject):
    finalized = Signal(object)
    def start_stage(self, session_id: str, stage: ProtocolStage) -> None: ...
    def stop(self, session_id: str) -> None: ...
    def finalize_after_last_stage(self, session_id: str) -> None: ...
```

Open transport/stager only for stage one. Copy every parsed frame to durable storage and display mailbox. Later stages change only UI boundaries. Last-stage countdown transitions to `FINALIZING`; quality/commit emits `CaptureFinalized` on the Qt thread. Invalid outcomes discard staging, close transport, release lease and show retry.

- [ ] **Step 4: Verify GREEN and commit**

Run `QT_QPA_PLATFORM=offscreen ./scripts/local-env.sh python -m pytest client/tests/test_live_hardware_acquisition.py client/tests/test_live_stage_finalization.py client/tests/test_ray_101_coordinator.py -q`; then commit changed ports/coordinator/controller/module/tests as `Connect staged UI flow to live hardware capture`.

### Task 4: Physical BASIC report and truthful result state

**Files:** Create `client/app/live_physical_reporting.py`; modify `client/app/ui_integration.py`, `client/app/qt_shell.py`; tests `client/tests/test_live_physical_reporting.py`, `client/tests/test_live_result_ui.py`.

**Consumes:** `process_committed_physical_session()`, `InstitutionLocalStore`, UI-derived `StaticBalanceProtocolContext`, current report delivery.

**Produces:** `LivePhysicalReportProcessor.process(session_id)` and `SyncPresentationStatus.PENDING`.

- [ ] **Step 1: Write failing tests**

```python
def test_committed_four_stage_session_creates_basic_report() -> None:
    outcome = processor.process("s-1")
    assert outcome.status is ProcessingStatus.BASIC_READY

def test_unacknowledged_upload_is_pending(qtbot) -> None:
    window.present_state(state_with_pending_sync)
    assert window.findChild(QLabel, "syncStatusBadge").text() == "待同步"
```

- [ ] **Step 2: Verify RED**

Run `QT_QPA_PLATFORM=offscreen ./scripts/local-env.sh python -m pytest client/tests/test_live_physical_reporting.py client/tests/test_live_result_ui.py -q`; expect imports to fail.

- [ ] **Step 3: Implement report adapter**

```python
class LivePhysicalReportProcessor:
    def process(self, session_id: str) -> ProcessingOutcome: ...
```

Build protocol context from explicit UI stage completions, reject absent/malformed completion records, persist only valid reports, and reuse `ReportConnectedController` for preview/export/print. Add `待同步`, never a false upload-success state.

- [ ] **Step 4: Verify GREEN and commit**

Run `QT_QPA_PLATFORM=offscreen ./scripts/local-env.sh python -m pytest client/tests/test_live_physical_reporting.py client/tests/test_live_result_ui.py client/tests/test_ray_85_physical_local.py -q`; then commit adapter, UI changes and tests as `Present committed physical reports in Qt`.

### Task 5: Default packaged assembly and public-only integration profile

**Files:** Create `client/app/live_institution_runtime.py`, `client/app/integration_profile.py`; modify `client/app/packaged_entry.py`, `main.py`; tests `client/tests/test_live_institution_runtime.py`, `client/tests/test_integration_profile.py`, `client/tests/test_ray_114_packaged_entry.py`.

**Consumes:** Tasks 1–4, `AccessRuntimeSettings`, startup validation and `build_connected_ui()`.

**Produces:** `LiveInstitutionScreeningRuntime.build_workbench()` and `IntegrationProfile`.

- [ ] **Step 1: Write failing tests**

```python
def test_authenticated_package_builds_live_workbench(tmp_path: Path) -> None:
    window = LiveInstitutionScreeningRuntime(...).build_workbench(session, passed_startup)
    assert window.property("dataSourceMode") == "LIVE_HARDWARE"

def test_profile_rejects_secret_field() -> None:
    with pytest.raises(ValueError, match="public-only"):
        IntegrationProfile.from_mapping({"base_url": URL, "refresh_token": "x"})
```

- [ ] **Step 2: Verify RED**

Run `QT_QPA_PLATFORM=offscreen ./scripts/local-env.sh python -m pytest client/tests/test_live_institution_runtime.py client/tests/test_integration_profile.py -q`; expect imports to fail.

- [ ] **Step 3: Implement default assembly**

```python
class LiveInstitutionScreeningRuntime:
    def build_workbench(self, session, startup_run) -> ScreeningWindow: ...
```

Pass this factory to the startup gate instead of bare `ScreeningWindow`. Preserve `--replay`; remove command-line live demo from the user-facing path. Profile contains base URL, CA path, public-key path, key ID and integration marker only; reject fields containing `password`, `token`, `secret`, `private_key`, `activation_code` or `dsn`.

- [ ] **Step 4: Verify GREEN and commit**

Run `QT_QPA_PLATFORM=offscreen ./scripts/local-env.sh python -m pytest client/tests/test_live_institution_runtime.py client/tests/test_integration_profile.py client/tests/test_ray_114_packaged_entry.py client/tests/test_seed_access_runtime.py -q`; then commit runtime/profile/entry/tests as `Compose live hardware workflow in packaged app`.

### Task 6: Full Qt regression and supervised UI acceptance

**Files:** Create `client/tests/test_live_full_ui_flow.py`; modify `client/tests/test_ray_101_ui_integration.py`, `docs/evidence/linear/RAY-100/README.md`, `docs/evidence/linear/RAY-101/README.md`.

**Consumes:** Task 5 default composition and serial/lease/physical test fakes.

**Produces:** reproducible full Qt coverage and bounded supervised evidence.

- [ ] **Step 1: Write failing full-UI test**

```python
def test_ui_reaches_report_from_inventory_activation(qtbot, runtime) -> None:
    fill_activation_form(runtime.access_window, asset_serial="FFP-DP4864-000001")
    click(runtime.access_window, "activateButton")
    complete_startup_gate(runtime)
    complete_anonymous_subject_and_consent(runtime.workbench)
    complete_four_visible_stages(runtime.workbench)
    assert runtime.workbench.current_page_id is PageId.RESULT
```

- [ ] **Step 2: Verify RED**

Run `QT_QPA_PLATFORM=offscreen ./scripts/local-env.sh python -m pytest client/tests/test_live_full_ui_flow.py -q`; expect the first unwired live-runtime boundary to fail.

- [ ] **Step 3: Add exact failure cases**

Add lease-conflict, disconnect, operator-stop, invalid-quality and pending-sync tests. Each must end without BASIC report and none may depend on USB serial or replay fixture.

- [ ] **Step 4: Verify and do supervised UI acceptance**

Run `QT_QPA_PLATFORM=offscreen ./scripts/local-env.sh python -m pytest client/tests/test_live_full_ui_flow.py client/tests/test_ray_101_ui_integration.py client/tests/test_live_hardware_acquisition.py client/tests/test_ray_85_physical_local.py client/tests/test_seed_access_runtime.py client/tests/test_ray_114_packaged_entry.py -q`.

Then use the packaged Qt app and the public-only integration profile: operator enters real inventory credentials in P-00, completes UI-directed stages and opens report. Evidence retains only screenshots, stage sequence, frame count/rate, lease success/release booleans, local commit/report booleans and `待同步`.

- [ ] **Step 5: Update evidence and commit**

Commit test/evidence files as `Verify full UI live hardware workflow`.

## Plan self-review

- Tasks 1–5 cover lease, encrypted local state, worker/UI synchronization, physical report, default entry and trust profile; Task 6 covers automated UI plus supervised integration evidence.
- Scope ends with `待同步` because cloud-ingestion acknowledgement is not currently composed; it does not add DNS/certificate work or clinical claims.
- Each task defines introduced types before consumers and includes a RED test, verification command and commit boundary.
