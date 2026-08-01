# RAY-105 Evidence

- Issue: `RAY-105` 设计系统与应用外壳
- Milestone: `P2：一键筛查`
- Status: `Done` on 2026-07-31.

## Delivered scope

- `client/app/design_system.py` supplies the medical-blue tokenized Qt theme, focus styles, action sizes, cards, status pills, and 1280×720-safe layout rules.
- `client/app/qt_shell.py` supplies the P-01 app header, global navigation, institution/device/sync summaries, central primary action, and recent-records view.
- The P-01 header is deliberately visible, including its institution, device, sync, and navigation controls; this was corrected after visual review.

## Automated and visual verification

- `client/tests/test_ui_design_system.py`, `test_ui_demo.py`, and `test_ray_101_qt_shell.py` pass (`16 passed` after the P-01 fix).
- `scripts/capture_ui_design.py` rendered P-01 at 1440×900; visual review confirmed the visible header and unobscured primary action.

## Boundary

The review is Qt offscreen only; target Windows scaling and live operator use remain separate delivery/field boundaries, not claims made by this completed local design-system issue.

## Commit

Implementation and evidence: `aa9162f` — `Add institution access entry UI`.

## 2026-07-31 hardware-independent closeout

- Fresh full client regression: `204 passed in 36.05s`; JUnit SHA-256 `1cff8bad710862943c8a61f17efce31425d54058a38233fd0a8e34525edb44b5`.
- Fresh full project regression: `592 passed, 3 warnings, 9 subtests passed in 40.44s`; JUnit SHA-256 `41e1e0dce034e778555ea22c4967b7ca716591e3d60e50425a04b6f84bd098ad`.
- P-01 was freshly captured and reviewed at both 1440×900 and 1280×720. The institution/device/sync header, navigation, recent-record table and central primary action remain visible. The ordinary UI exposes no serial path, queue, log or internal quality threshold.
- The earlier Windows/field boundary is not part of this issue's stated acceptance. It remains a later package/operator acceptance boundary and does not block completion of this local PySide6 design-system task.
