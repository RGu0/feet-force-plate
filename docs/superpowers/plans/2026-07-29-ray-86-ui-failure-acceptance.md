# RAY-86 Hardware UI Failure Acceptance Plan

> **For Codex:** Required sub-skill: use `superpowers:executing-plans` to execute this plan task-by-task.

**Goal:** Close the automatable part of RAY-86's remaining acceptance gap by carrying the already-sanitized `HardwareUiFailure` object into the operator workflow and rendering its recovery instruction without exposing technical details.

**Architecture:** Keep `client.device.session_ui` as the sole hardware-side safe DTO. Add a thin app-layer resolver that translates its stable enum values into existing workflow `ClientError` values. The coordinator owns invalid/incomplete session closure and telemetry, while the Qt result page renders the safe operator message and enables retry only when the resolved action permits it.

**Tech Stack:** Python 3.12, PySide6, pytest/pytest-qt, ruff, mypy.

## Global constraints

- Use `bash scripts/local-env.sh` for every Python/test command; do not create a repository `.venv`.
- Do not pass raw transport errors, serial paths, protocol details, raw frames, matrices, or audit details to UI/workflow state.
- Keep `HardwareUiFailure` as the hardware-to-application boundary; telemetry records only a stable application code.
- Preserve the existing legacy disconnect callback; this work adds the typed path rather than rewriting unrelated runtime integration.
- RAY-86 remains **In Review** after automation: a human must still visually execute the operator flow against the built application before Done.

## Task 1: Specify the typed handoff with a failing test

**Files:**
- Create: `client/tests/test_ray_86_hardware_ui.py`
- Modify: `client/tests/test_ray_101_controller.py`

1. Add a focused app-layer test for a retryable `HardwareUiFailure` that asserts a stable `ClientError`, no technical content, and the retry action.
2. Add a controller/UI test which sends the typed failure while acquiring and asserts the result page shows the operator instruction and retry control.
3. Run the focused test and confirm it fails because the typed handoff does not yet exist.

## Task 2: Implement the smallest safe typed path

**Files:**
- Create: `client/app/hardware_failure.py`
- Modify: `client/workflow/coordinator.py`
- Modify: `client/app/controller.py`
- Modify: `client/app/qt_shell.py`

1. Map every `HardwareUiFailureCode` to an existing-safe workflow error code, message, and action, with no hardware detail copied through.
2. Add `ScreeningCoordinator.handle_hardware_failure(...)` to record a stable telemetry code, mark only an active acquisition incomplete, and retain no invalid capture for report/analysis.
3. Expose the typed callback in `ApplicationController` and update its coordinator protocol.
4. Render `state.error.operator_message` on the result page; show retry only for `RETRY_SCREENING`, while support-only failures remain safely visible with return-to-workbench.

## Task 3: Verify recovery variants and safety boundaries

**Files:**
- Modify: `client/tests/test_ray_86_hardware_ui.py`
- Modify: `client/tests/test_ray_101_coordinator.py`

1. Add a support-only finalization/processing failure case that does not expose a raw exception and hides retry.
2. Add a coordinator integration case proving the typed event marks the session incomplete, emits only a stable telemetry detail, and does not produce a report.
3. Run focused tests, then relevant client/device/hardware suites, static checks, and a Qt screenshot inspection.

## Task 4: Record evidence and synchronize Linear

**Files:**
- Modify: `docs/evidence/linear/RAY-86/README.md`
- Create: `docs/evidence/linear/RAY-86/2026-07-29-hardware-ui-consumption.md`

1. Record exact commands/results, the automated/manual boundary, and the no-raw-data guarantee.
2. Commit only the implementation, tests, plan, and RAY-86 evidence.
3. Comment on RAY-86 with the evidence and keep it **In Review**, explicitly naming the remaining human operator-flow check.

## Verification checklist

- [ ] Every new production function/method first had a focused test that failed for the missing behavior.
- [ ] Retryable and support-only hardware failures have distinct, safe operator outcomes.
- [ ] No raw/technical hardware detail appears in workflow state or Qt result text.
- [ ] Focused and relevant regression suites pass through the project wrapper.
- [ ] ruff, mypy, pre-commit, `uv lock --check`, and `git diff --check` pass.
- [ ] RAY-86 evidence and Linear state accurately retain the manual acceptance boundary.
