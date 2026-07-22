# RAY-114 Evidence — 启动设备初始化状态机与进度页面

## Issue snapshot

- Linear issue: RAY-114
- Status captured before implementation completion: `In Progress`
- Dependency: RAY-113 (`In Review`, implementation commit `0fd1b4d`)
- Approved design: `docs/superpowers/specs/2026-07-21-startup-device-validation-design.md` (`7c089a9`)
- Structured snapshot: `issue-snapshot.json`

## Implementation

- `client/startup_validation/workflow.py`
  - mandatory BOOTSTRAPPING → CONNECTING → WAITING_FOR_EMPTY → COLLECTING_BASELINE → VALIDATING → PASSED flow;
  - plain-language mappings for all requested failure states and stable public diagnostic codes;
  - gate opens only for `PASS`; retry retains audit linkage but creates a fresh device connection and validation run.
- `client/startup_validation/serial_connector.py`
  - uses the production CH340 discovery, `SerialByteTransport`, `DaoOneP4864Parser`, and observed 3079-byte/48×64 raw contract;
  - exposes only an opaque hash-derived device reference to the validation record.
- `client/app/startup_validation.py`
  - single-page Steady Health launch screen with the existing 64 px brand header, type hierarchy, color tokens, spacing, 12 px card radius, progress bar, status assets, buttons, and copy tone;
  - indeterminate connection progress and host-monotonic-derived determinate collection progress/countdown;
  - one primary recovery action on failure, plus a separate safe-exit action; no skip action;
  - asynchronous worker boundary keeps the Qt UI responsive, and creates the workbench only after a passing run.
- `client/app/packaged_entry.py`
  - replaces the package placeholder entry with the mandatory startup gate;
  - local validation has no network dependency.
- `client/app/packaging/FeetForcePlate.spec`
  - packages runtime logo and status assets from `client/app/assets/`.
- `scripts/capture_startup_validation.py`
  - deterministic capture for connection, 5-second collection, pass, failure, and long-copy states.

Implementation commit: `35c691f4d35676ee5a42895fd4b55ac2f6082a32`

## Automated verification

Primary matrix:

```text
./scripts/local-env.sh python -m pytest tests/startup_validation tests/device \
  client/tests/test_ray_114_startup_ui.py \
  client/tests/test_ray_114_packaged_gate.py \
  client/tests/test_ray_114_packaged_entry.py \
  -q --junitxml=docs/evidence/linear/RAY-114/pytest-results.xml
```

Result: **68 passed**. JUnit: `pytest-results.xml`.

Existing workbench UI compatibility:

```text
./scripts/local-env.sh python -m pytest \
  client/tests/test_ui_design_system.py \
  client/tests/test_ui_demo.py \
  client/tests/test_ui_read_models.py \
  client/tests/test_ray_101_qt_shell.py \
  client/tests/test_ray_101_controller.py \
  -q --junitxml=docs/evidence/linear/RAY-114/pytest-ui-regression-results.xml
```

Result: **27 passed**. JUnit: `pytest-ui-regression-results.xml`.

Covered automatically:

- success-state order and all requested public failure mappings;
- workbench creation only after `PASS`;
- no-device, occupied-device, and open-race handling;
- retry uses a fresh connection/run context;
- no customer-facing CheckSum, threshold, bad-point, stack, or port details;
- keyboard focus lands on the one primary recovery action;
- no skip control exists;
- 1280×720 minimum layout, long-copy wrapping, runtime assets, and package asset declaration;
- RAY-113 baseline service/parser/device regressions.

## Repeatable UI capture and visual review

Standard capture command:

```text
./scripts/local-env.sh python scripts/capture_startup_validation.py \
  --output-dir docs/evidence/linear/RAY-114/ui
```

2× Qt scale-factor capture command:

```text
QT_SCALE_FACTOR=2 ./scripts/local-env.sh python scripts/capture_startup_validation.py \
  --output-dir docs/evidence/linear/RAY-114/ui-hidpi
```

Reviewed captures:

- `ui/connecting-1440x900.png`: single-page shell, brand header, indeterminate progress, safe exit.
- `ui/collecting-1440x900.png`: 50% determinate progress and 3-second rounded-up countdown.
- `ui/passed-1440x900.png`: existing success icon, 100% progress, no action that could bypass the gate.
- `ui/failure-1440x900.png`: plain explanation, stable diagnostic number, one primary recovery action.
- `ui/long-copy-1280x720.png`: wrapped copy remains inside the reading width; action and safe exit remain visible.
- `ui-hidpi/`: the same five states rendered with `QT_SCALE_FACTOR=2`; the long-copy capture was visually inspected for clipping, spacing, and readable hierarchy.

Visual review result: no clipping or overflow observed at 1440×900 or 1280×720; progress, countdown, diagnostic number, action hierarchy, header/footer, and long Chinese copy remain legible. The page uses the existing Steady Health visual system and does not add global navigation.

## Verification boundary

Automated and local visual checks are complete. The following remain explicitly unverified:

- real DO-P4864 hardware timing and real disconnect/reconnect behavior;
- a real Windows target with CH340 driver, Windows high DPI, and screen scaling;
- manual keyboard-only and screen-reader acceptance on the target OS;
- operator usability in a clinic/elder-care workflow;
- signed/notarized packaged build and installer asset smoke test;
- RAY-115 durable log/telemetry persistence and delayed-upload integration.

Therefore RAY-114 may move to **In Review**, not Done.
