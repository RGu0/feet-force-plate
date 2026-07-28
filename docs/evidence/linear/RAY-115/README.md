# RAY-115 Evidence — 启动校验失败恢复、内部日志与验收证据

## Issue snapshot

- Linear issue: RAY-115
- Status captured during implementation: `In Progress`
- Dependencies: RAY-113 and RAY-114 (`In Review`)
- Approved design: `docs/superpowers/specs/2026-07-21-startup-device-validation-design.md` (`7c089a9`)
- Structured snapshot: `issue-snapshot.json`

## Implementation

- `client/spool/state_store.py`
  - additive SQLite schema migration 1 → 2;
  - durable `device_validation_runs` table for versioned safe summaries;
  - separate `telemetry_events` queue with PENDING / UPLOADING / ACKNOWLEDGED / QUARANTINED states;
  - interrupted UPLOADING telemetry is returned to PENDING with an incremented attempt count.
- `client/startup_validation/persistence.py`
  - canonical JSON allow-listed from `DeviceValidationRun.safe_summary()`;
  - rejects raw device paths and accepts only opaque terminal/device references;
  - atomically saves the local audit row and queues the upload event;
  - upload failure changes only queue state and never mutates the local validation result.
- `client/startup_validation/recovery.py`
  - versioned `startup-failure-escalation/1` policy;
  - the third consecutive signal-class failure becomes `SERVICE_REQUIRED`;
  - pass, stream, connection, or load conditions break/do not enter the signal escalation chain.
- `client/startup_validation/workflow.py`
  - applies the versioned policy before writing the audit record;
  - records successful, service, device-discovery, occupied-device, and internal-error runs;
  - blocks the workbench for every non-PASS outcome.
- `client/app/packaged_entry.py`
  - production package composition opens the persistent local state database;
  - injects the audit trail and persisted-history escalation policy into the mandatory gate;
  - does not attempt network upload on the startup critical path.
- `client/app/startup_validation.py`
  - customer-safe SERVICE_REQUIRED page and all requested recovery pages;
  - stable diagnostic number, one primary recovery action, safe exit, and no protocol/debug details.
- `scripts/capture_startup_failure_states.py`
  - deterministic capture of all seven public failure/recovery states.

Implementation commit: `ef26fdb7447ed951ab9322a4dc08bc746675c617`

## Automated verification

Primary failure, persistence, startup, device, and spool matrix:

```text
./scripts/local-env.sh python -m pytest \
  tests/startup_validation tests/device tests/spool \
  client/tests/test_ray_114_startup_ui.py \
  client/tests/test_ray_114_packaged_gate.py \
  client/tests/test_ray_114_packaged_entry.py \
  -q --junitxml=docs/evidence/linear/RAY-115/pytest-results.xml
```

Result: **102 passed**. JUnit: `pytest-results.xml`.

Existing workbench UI compatibility:

```text
./scripts/local-env.sh python -m pytest \
  client/tests/test_ui_design_system.py \
  client/tests/test_ui_demo.py \
  client/tests/test_ui_read_models.py \
  client/tests/test_ray_101_qt_shell.py \
  client/tests/test_ray_101_controller.py \
  -q --junitxml=docs/evidence/linear/RAY-115/pytest-ui-regression-results.xml
```

Result: **27 passed**. JUnit: `pytest-ui-regression-results.xml`.

Full repository regression:

```text
./scripts/local-env.sh python -m pytest -q \
  --junitxml=docs/evidence/linear/RAY-115/pytest-full-regression-results.xml
```

Result: **215 passed**. JUnit: `pytest-full-regression-results.xml`.

Covered automatically:

- no device, occupied device/open race, load, disconnect, no data/stall, low rate, large host gap, fixed area, saturation, no variation, local anomaly, noise, drift, internal exception, retry, and later success;
- partial 5-second windows are marked discarded and never pass;
- retry starts a fresh connection/run and retains only audit linkage;
- stable `E-INI-006` with unique diagnostic IDs and no exception message in public copy;
- SQLite schema-1 upgrade to schema 2 without dropping existing tables;
- local safe summary + upload event atomicity, upload-failure requeue, and startup recovery;
- pass/non-signal reset and third consecutive signal failure escalation;
- one recovery button, safe exit, no skip, and no CheckSum, threshold, bad-point, stack, raw port, or trace text in customer UI.

## Safe log example and privacy review

- Sample: `safe-telemetry-sample.json`
- Contains only opaque run/terminal/device references, versions, outcome/reason/error/diagnostic codes, timestamps, bounded aggregate statistics, transitions, and partial-window flag.
- Does not contain names, institution record numbers, raw serial paths, raw matrices, per-sensor bad-point detail, threshold values, protocol error text, debug curves, or stack traces.
- The threshold and failure policy are logged by version identifier, not by mutable numeric values.

## Repeatable UI capture and visual review

```text
./scripts/local-env.sh python scripts/capture_startup_failure_states.py \
  --output-dir docs/evidence/linear/RAY-115/ui
```

Reviewed 1440×900 captures:

- `ui/device-not-found.png`
- `ui/device-busy.png`
- `ui/load-not-empty.png`
- `ui/stream-interrupted.png`
- `ui/signal-invalid.png`
- `ui/service-required.png`
- `ui/internal-error.png`

Visual review result: all states remain within the existing Steady Health shell, show one plain-language recovery action and safe exit, keep the stable diagnostic number readable, and do not expose internal details. No clipping or overflow was observed. RAY-114 separately records 1280×720 long-copy and 2× Qt scale-factor capture.

## Verification boundary

Automated failure injection, local persistence, queue state behavior, and local visual review are complete. The following remain explicitly unverified:

- repeated cold starts and fault injection on a real DO-P4864;
- physical load during collection, real cable removal/reconnection, and proof from live device logs;
- Windows target with CH340 driver, Windows high DPI, keyboard-only, screen reader, and safe-exit acceptance;
- clinic/elder-care operator usability;
- a real telemetry upload worker/server, authentication, retry/backoff, and server acknowledgement end to end;
- signed installer, upgrade/rollback, and database migration on the target OS.

Therefore RAY-115 may move to **In Review**, not Done.

## 2026-07-26 发布阻断复核

- 修复：`StartupValidationCoordinator` 在调用可能失败的 audit/SQLite sink 前先保留本次运行。sink 失败会呈现安全的 `INTERNAL_ERROR`，阻止进入工作台；`retry()` 仍带前一次 run ID，重新连接并创建新运行。
- 测试：新增 audit 写入失败 → 新连接 → 后续成功的链路断言；定向 **22 passed in 0.49s**，启动/设备/入口组合 **112 passed in 1.00s**，全量 **336 passed in 28.03s**。
- 限制：未进行真机故障注入、真实 SQLite 损坏恢复、Windows/CH340 或遥测服务端确认；RAY-115 保持 In Review。
- Commit SHA：尚未创建；本轮未暂存。
