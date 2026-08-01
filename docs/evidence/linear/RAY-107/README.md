# RAY-107 Evidence

- Issue: `RAY-107` 检测记录与设备支持（P-09、P-11）
- Milestone: `P2：一键筛查`
- Status: `Done` on 2026-07-31.

## Delivered scope

- P-09 provides institution-scoped read-model filtering by masked identifier, date, and report status, with a report action pinned to `report_id + version`.
- P-11 presents device, sync, pending-data, and app-version summaries plus safe recheck/diagnostic actions.
- Operator pages expose neither serial, queue, log, configuration-signature, nor internal-quality details.

## Verification

`client/tests/test_ui_read_models.py`, `test_ray_101_controller.py`, and `test_ray_101_qt_shell.py` pass in the P2 regression. P-09 and P-11 were rendered by the deterministic offscreen capture tool.

## Boundary

The read models are development/test adapters; real institution isolation, diagnostic export handling, and operator acceptance still need integration validation.

## Commit

Implementation and evidence: `aa9162f` — `Add institution access entry UI`.

## 2026-07-31 hardware-independent closeout

- Fresh full client regression: `204 passed in 36.05s`; full project regression: `592 passed, 3 warnings, 9 subtests passed in 40.44s`.
- Fresh P-09 and P-11 captures were generated at 1440×900 and 1280×720. Records filtering/view actions remain read-model driven and report references remain pinned; support actions and summaries expose no serial, queue, log, signature or internal-quality details.
- RAY-107 implements and tests the UI/read-model boundary. A production tenant store or diagnostic exporter is an adapter/integration concern outside this issue and is not represented by the development fixtures.
