# RAY-107 Evidence

- Issue: `RAY-107` 检测记录与设备支持（P-09、P-11）
- Milestone: `P2：一键筛查`
- Status: `In Review`

## Delivered scope

- P-09 provides institution-scoped read-model filtering by masked identifier, date, and report status, with a report action pinned to `report_id + version`.
- P-11 presents device, sync, pending-data, and app-version summaries plus safe recheck/diagnostic actions.
- Operator pages expose neither serial, queue, log, configuration-signature, nor internal-quality details.

## Verification

`client/tests/test_ui_read_models.py`, `test_ray_101_controller.py`, and `test_ray_101_qt_shell.py` pass in the P2 regression. P-09 and P-11 were rendered by the deterministic offscreen capture tool.

## Boundary

The read models are development/test adapters; real institution isolation, diagnostic export handling, and operator acceptance still need integration validation.

