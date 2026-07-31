# RAY-112 Evidence

- Issue: `RAY-112` 视觉回归与可用性验收
- Milestone: `P2：一键筛查`
- Status: `In Review`

## Automated visual regression

- `scripts/capture_ui_design.py` deterministically renders 15 P-01–P-11 states at 1440×900, including conflict, preflight-failure, stop-confirmation, and invalid-result states.
- The full `client/tests` regression exercises accessible action targets, navigation locking, minimum action sizes, safe error copy, read-model boundaries, and reporting/version-pinning behavior.
- Manual offscreen review covered P-01, P-03, P-06, P-07, P-08, and P-10. The workbench header defect discovered in this review was fixed and covered by `test_workbench_has_source_topbar_statuses_and_central_primary_action`.

## Boundary

This is not target Windows high-DPI, keyboard/screen-reader, real-device, physical-printer, or non-technical-operator acceptance. Those required observations keep this item `In Review`.

## Commit

Implementation and evidence: `aa9162f` — `Add institution access entry UI`.
