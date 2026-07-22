# RAY-117 evidence

## Scope and status

- Linear status: `In Progress` (confirmed 2026-07-22).
- Contract under implementation: `physical-array-session/1.0`.
- Hardware scope: board-plane geometry, immutable raw counts, 5-second unloaded zero/noise reference, relative-load values, host-monotonic time, quality, provenance, and uncertainty.
- Withheld: body ML/AP, COP, motion/clinical metrics, absolute N/Pa, and electrical active area.

## User-provided geometry evidence

- Source file: `user-provided-sensor-geometry-20260721.png`.
- SHA-256: `d3826b1f78e9d546ee891560f4f357767e7ced199decef2bbcec0ec09631f6bd`.
- User-confirmed coordinate convention: first upper-left point is `(0, 0) mm`; x increases right; y increases down; both pitches are `7.99 mm`.
- Supplier-image values are source metadata only: approximate sensing region `381.3 x 509.3 mm`, nominal point `6 x 6 mm`, and legacy listed spacing `7 x 7 mm`.

## Dependency boundary

RAY-78 confirms only the decoded compact `uint8` array and column-major point ordering. RAY-113 confirms startup validation but its current `DeviceValidationRun` persists summary/statistics rather than raw baseline frames. RAY-117 therefore tests an immutable baseline-window port; production handoff remains pending RAY-113 support.

## Verification log

- 2026-07-22: restored the authoritative project-local `scripts/local-env.sh`, `.python-version`, `pyproject.toml`, and locked `uv.lock`; verified `Python 3.11`, NumPy `2.4.6`, pytest `9.1.1` through the wrapper.
- PASS: `./scripts/local-env.sh python -m pytest tests/hardware_standardization tests/device/test_protocol.py tests/startup_validation -q --junitxml=docs/evidence/linear/RAY-117/pytest-results.xml` — 61 passed.
- PASS: `git diff --check`; JSON Schema parsed with `python -m json.tool`; the generic package contains no ML/AP, COP, motion, risk, or report symbols.
- PARTIAL: `./scripts/local-env.sh python -m pytest -q --junitxml=docs/evidence/linear/RAY-117/pytest-full-regression-results.xml` — 211 passed, 1 failed. The only failure is existing UI test `client/tests/test_ray_101_ui_integration.py::test_connected_controller_loads_the_exact_report_document_into_p10`, whose expected `基础 v2` footer differs from current UI footer `报告编号 report-ui-1 · v2 · …`. RAY-117 does not modify UI/report code and does not mask this failure.

## Completion boundary

- Automated physical-array contract, baseline calculation, generic/DO-P4864 adapters, serialization, schema and dependency-boundary checks are complete.
- Production RAY-113 baseline-window handoff, real-device baseline repeatability, known-load count-to-N/Pa calibration, active-area validation, saturation/bad-point thresholds, time uncertainty, coordinate direction and cross-device validation remain unverified.
- The issue must remain `In Review`; it must not be marked `Done`.
