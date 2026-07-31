# RAY-105 Evidence

- Issue: `RAY-105` 设计系统与应用外壳
- Milestone: `P2：一键筛查`
- Status: `In Review`

## Delivered scope

- `client/app/design_system.py` supplies the medical-blue tokenized Qt theme, focus styles, action sizes, cards, status pills, and 1280×720-safe layout rules.
- `client/app/qt_shell.py` supplies the P-01 app header, global navigation, institution/device/sync summaries, central primary action, and recent-records view.
- The P-01 header is deliberately visible, including its institution, device, sync, and navigation controls; this was corrected after visual review.

## Automated and visual verification

- `client/tests/test_ui_design_system.py`, `test_ui_demo.py`, and `test_ray_101_qt_shell.py` pass (`16 passed` after the P-01 fix).
- `scripts/capture_ui_design.py` rendered P-01 at 1440×900; visual review confirmed the visible header and unobscured primary action.

## Boundary

The review is Qt offscreen only; target Windows scaling and live operator use remain required before `Done`.

