# RAY-109 Evidence

- Issue: `RAY-109` 结果与报告预览（P-08、P-10）
- Milestone: `P2：一键筛查`
- Status: `Done` on 2026-07-31.

## Delivered scope

- P-08 distinguishes BASIC_READY, deferred full analysis, and invalid/retest paths; quality failure does not claim a completed customer report.
- P-10 renders the selected `BasicReportDocument` and preserves its exact `report_id + version` for preview, PDF export, and printing.
- The UI keeps a next-screening action available while later analysis is pending.

## Verification

`client/tests/test_ray_101_ui_integration.py`, `test_ray_101_qt_shell.py`, `test_ray_85_reporting.py`, and `test_ray_96_pdf_delivery.py` pass in the P2 regression. P-08 and P-10 were rendered and visually reviewed offscreen.

## Boundary

Offscreen PDF/preview tests do not validate an actual printer, production-cloud analysis, or a clinically validated full report.

## Commit

Implementation and evidence: `aa9162f` — `Add institution access entry UI`.

## 2026-07-31 hardware-independent closeout

- Fresh full client regression: `204 passed in 36.05s`; full project regression: `592 passed, 3 warnings, 9 subtests passed in 40.44s`.
- Fresh P-08 success/failure and P-10 report captures were generated at both target sizes. Manual review confirmed that invalid input has a retest path and no customer report, while BASIC_READY offers the next-screening action and the selected report version stays visible with export/print actions.
- This completes the result/report UI and controller contract only. It does not claim a physical printer, production-cloud analysis or a clinically validated complete report.
