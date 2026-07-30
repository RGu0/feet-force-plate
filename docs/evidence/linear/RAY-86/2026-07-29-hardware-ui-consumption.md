# RAY-86 — HardwareUiFailure application/UI consumption

- Issue snapshot: `RAY-86` / `可靠采集监控与 P1 验收`
- Linear status when captured: `In Review`
- P1 milestone: `P1：可靠采集`
- Captured: 2026-07-29
- Implementation commit: `63aad63` (`Wire RAY-86 hardware failures to UI`)

## Implemented boundary

`client.device.session_ui.HardwareUiFailure` remains the only hardware-to-application
payload. `client.app.hardware_failure.resolve_hardware_ui_failure(...)` maps its stable
enum code to a stable workflow error code, localized operator message and either
`RETRY_SCREENING` or `CONTACT_SUPPORT`.

`ApplicationController.on_hardware_failure(...)` passes only that resolved error to the
workflow coordinator. During an active acquisition, the coordinator marks the session
incomplete and records the stable `hardware_ui_failure:<application-code>` audit value.
No serial path, raw exception, protocol detail, raw frame, matrix or bad-point detail is
copied into UI state or the UI-facing telemetry value.

The Qt result page renders the safe message. It offers **重新检测** only when the resolved
action permits retry; support-only errors retain a safe return path and direct the operator to
contact support. An unrelated invalid state with no explicit error retains the historical retry
behavior.

## Test-first record

The following tests were written before the corresponding production behavior and observed to
fail for the expected missing behavior:

1. Importing the app-level resolver failed because the module did not exist.
2. A support-only local-finalization failure incorrectly showed **重新检测** before the
   action-gated presentation logic was added.
3. The coordinator test failed with no `handle_hardware_failure` method before that typed closure
   path was implemented.
4. A support-only failure initially displayed the inaccurate quality-gate label; it now renders
   the neutral **本次检测未完成** label.

Focused post-change command:

```text
bash scripts/local-env.sh python -m pytest client/tests/test_ray_86_hardware_ui.py client/tests/test_ray_101_controller.py client/tests/test_ray_101_coordinator.py client/tests/test_ray_101_qt_shell.py client/tests/test_ray_91_qt.py tests/device/test_session_ui.py tests/device/test_session_runtime.py -q
```

Result: **46 passed in 1.59s**.

Current P1 hardware/storage/startup regression:

```text
bash scripts/local-env.sh python -m pytest tests/device tests/spool tests/hardware_standardization tests/startup_validation -q
```

Result: **183 passed in 1.46s**.

Client regression was rerun in three stable file groups because a combined GUI run has a
pre-existing test-order-dependent focus timeout in
`client/tests/test_ray_114_startup_ui.py::test_failure_has_plain_copy_one_primary_recovery_and_safe_exit`:
the combined first group produced **76 passed, 1 focus timeout**, while the same test alone
passed (**1 passed**) and the three RAY-114 files together passed (**10 passed**). The other two
client groups passed (**60 passed** and **50 passed**). This timeout is outside the RAY-86 failure
path and no RAY-114 source/test was changed here.

Static verification passed:

```text
bash scripts/local-env.sh ruff check client/app client/workflow client/device client/tests/test_ray_86_hardware_ui.py client/tests/test_ray_101_coordinator.py
bash scripts/local-env.sh mypy
bash scripts/local-env.sh pre-commit run --all-files
uv lock --check
git diff --check
```

`ruff`, configured `mypy` targets (3 source files), pre-commit, lock consistency and diff checks
all passed.

## Visual operator-path check

An offscreen Qt result-page render was generated from a typed
`LOCAL_FINALIZATION_FAILED` / `CONTACT_SUPPORT` failure and visually inspected. It showed the
safe local-save/support instruction, stable `E-DAT-102` banner code, neutral **本次检测未完成**
state, no **重新检测** button, and no technical detail. The screenshot was local-only at
`/private/tmp/ray86-hardware-ui-support.png`; it contains no raw data and is not committed.

## Boundaries and remaining acceptance

This update did not open the serial device or create a new physical capture. The real 10-minute,
cable-removal, disk-full and controlled-restart evidence remains documented in this issue's README
and dated artifacts.

The controller entry point and visible operator behavior are now automated and visually checked,
but a person still needs to exercise this callback through the deployed application composition
and acknowledge the retry/support instruction before RAY-86 can be marked `Done`. Therefore the
Linear issue remains **In Review**.
