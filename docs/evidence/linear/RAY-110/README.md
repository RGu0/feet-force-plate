# RAY-110 Evidence

- Issue: `RAY-110` 检测中体验（P-07）
- Milestone: `P2：一键筛查`
- Status: `Done` on 2026-07-31.

## Delivered scope

- P-07 uses a focused heatmap-and-guidance layout with redundant COP/load/frame text, remaining time, an accessible state, and one protected stop action.
- Acquisition locks global navigation; stop requires a brief inline confirmation.
- The UI only consumes latest-only display frames and cannot write reliable capture or upload state.

## Verification

`client/tests/test_ray_84_*.py`, `test_ray_91_qt.py`, and `test_ray_101_qt_shell.py` pass in the P2 regression. The 1440×900 P-07 offscreen capture was visually reviewed for layout, countdown, text redundancy, and the separated stop action.

## Boundary

This does not replace real DO-P4864 cadence, Windows high-DPI, or field-operator safety acceptance.

## Commit

Implementation and evidence: `aa9162f` — `Add institution access entry UI`.

## 2026-07-31 hardware-independent closeout

- Fresh full client regression: `204 passed in 36.05s`; full project regression: `592 passed, 3 warnings, 9 subtests passed in 40.44s`.
- Fresh P-07 and stop-confirmation captures were generated at 1440×900 and 1280×720. Manual review confirmed the dual-column layout, stage/remaining-time text, replay-debug provenance, accessible redundant status and one protected stop action.
- The device-disconnect safe route and latest-only UI boundary are covered by the current Qt/controller suite. Real DO-P4864 cadence and field safety remain RAY-84/physical acceptance work and are not claimed here.
