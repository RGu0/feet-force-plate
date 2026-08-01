# RAY-106 Evidence

- Issue: `RAY-106` UI 只读模型与演示启动组合
- Milestone: `P2：一键筛查`
- Status: `Done` on 2026-07-31.

## Delivered scope

- Immutable dashboard, record, report-preview, and support DTOs live in `client/app/ui_models.py`.
- `ApplicationController` and `ScreeningWindow` consume optional read models through UI methods, without importing direct persistence, device, or network clients.
- `client/app/demo.py` provides an explicitly local development demo for page navigation, records, heatmap, and versioned report preview.

## Verification

`client/tests/test_ui_read_models.py` and `client/tests/test_ui_demo.py` pass in the P2 client regression. The development-demo capture was visually reviewed only as a design/flow check, not as a production runtime claim.

## Boundary

The demo does not substitute for a real device, persistent storage, sync, or cloud adapter.

## Commit

Implementation and evidence: `aa9162f` — `Add institution access entry UI`.

## 2026-07-31 hardware-independent closeout

- Fresh full client regression: `204 passed in 36.05s`; full project regression: `592 passed, 3 warnings, 9 subtests passed in 40.44s`.
- `main.py --demo` still provides the explicitly selected development composition; the default package entry remains separate and does not silently start demo or replay data.
- The current architecture boundary test is included in the full project run and locks application/local-analysis code away from concrete device, serial and protocol implementations.
- Real device, persistence, sync and cloud adapters are explicitly outside RAY-106's stated scope, so their absence is retained as a boundary rather than a completion blocker.
