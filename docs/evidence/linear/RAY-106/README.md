# RAY-106 Evidence

- Issue: `RAY-106` UI 只读模型与演示启动组合
- Milestone: `P2：一键筛查`
- Status: `In Review`

## Delivered scope

- Immutable dashboard, record, report-preview, and support DTOs live in `client/app/ui_models.py`.
- `ApplicationController` and `ScreeningWindow` consume optional read models through UI methods, without importing direct persistence, device, or network clients.
- `client/app/demo.py` provides an explicitly local development demo for page navigation, records, heatmap, and versioned report preview.

## Verification

`client/tests/test_ui_read_models.py` and `client/tests/test_ui_demo.py` pass in the P2 client regression. The development-demo capture was visually reviewed only as a design/flow check, not as a production runtime claim.

## Boundary

The demo does not substitute for a real device, persistent storage, sync, or cloud adapter.

