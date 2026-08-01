# RAY-112 Evidence

- Issue: `RAY-112` 视觉回归与可用性验收
- Milestone: `P2：一键筛查`
- Status: `Done` on 2026-07-31.

## Automated visual regression

- `scripts/capture_ui_design.py` deterministically renders 15 P-01–P-11 states at 1440×900, including conflict, preflight-failure, stop-confirmation, and invalid-result states.
- The full `client/tests` regression exercises accessible action targets, navigation locking, minimum action sizes, safe error copy, read-model boundaries, and reporting/version-pinning behavior.
- Manual offscreen review covered P-01, P-03, P-06, P-07, P-08, and P-10. The workbench header defect discovered in this review was fixed and covered by `test_workbench_has_source_topbar_statuses_and_central_primary_action`.

## Boundary

This is not target Windows high-DPI, keyboard/screen-reader, real-device, physical-printer, or non-technical-operator acceptance. RAY-112's own acceptance requires these boundaries to be recorded, not completed; the actual delivery/field observations remain tracked elsewhere.

## Commit

Implementation and evidence: `aa9162f` — `Add institution access entry UI`.

## 2026-07-31 hardware-independent closeout

The capture tool now accepts explicit `--width` and `--height` parameters. It generated all 15 deterministic P-01–P-11 states twice: 30 non-empty PNG files, with every image verified as exactly 1440×900 or 1280×720.

Manual review covered the required P-01, P-03, P-06, P-07, P-08 and P-10 states at both sizes. Primary actions remain visible; stop confirmation and invalid-result recovery remain explicit; ordinary pages do not expose serial paths, queues, logs, raw matrices or internal thresholds. The two capture runs emitted only a local missing generic font-alias performance warning and no render failure.

- `client/tests`: `204 passed in 36.05s`; JUnit SHA-256 `1cff8bad710862943c8a61f17efce31425d54058a38233fd0a8e34525edb44b5`.
- Full project: `592 passed, 3 warnings, 9 subtests passed in 40.44s`; JUnit SHA-256 `41e1e0dce034e778555ea22c4967b7ca716591e3d60e50425a04b6f84bd098ad`.
- Ruff for the capture tool: `All checks passed!`; `git diff --check` passed before the evidence update.

Per the issue's own acceptance text, real hardware, target Windows high DPI, physical printing and onsite operator use are recorded as unverified boundaries; they are not required to complete this automated/offscreen visual-regression task.
