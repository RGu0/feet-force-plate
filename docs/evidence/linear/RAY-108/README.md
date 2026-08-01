# RAY-108 Evidence

- Issue: `RAY-108` 建档与授权页面（P-02～P-04）
- Milestone: `P2：一键筛查`
- Status: `Done` on 2026-07-31.

## Delivered scope

- P-02 supports institution identifier types, masked lookup, controlled conflict handling, and anonymous quick creation.
- P-03 keeps identity and health fields optional while preserving explicit missing-value semantics.
- P-04 separates required screening consent from optional research consent; neither is preselected.

## Verification

`client/tests/test_ray_92_*.py`, `test_ui_design_system.py`, and `test_ray_101_qt_shell.py` pass in the P2 regression. Offscreen P-02/P-03/P-04 captures were visually checked for readable, unobscured primary actions and explicit consent/field-state affordances.

## Boundary

Actual institution authorization text, persistent cross-tenant isolation, and in-person usability remain external acceptance work.

## Commit

Implementation and evidence: `aa9162f` — `Add institution access entry UI`.

## 2026-07-31 hardware-independent closeout

- Fresh full client regression: `204 passed in 36.05s`; full project regression: `592 passed, 3 warnings, 9 subtests passed in 40.44s`.
- Fresh P-02, conflict, P-03 and P-04 captures were generated at 1440×900 and 1280×720. Manual review confirmed visible correction/continuation actions, optional identity fields, explicit missing-value semantics, and two unselected consent choices.
- Formal institution policy approval and persistent tenant isolation remain outside this page-implementation task. This evidence does not claim either one.
