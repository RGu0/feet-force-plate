# RAY-104 Evidence

- Issue: `RAY-104` UI Design 实施：机构端足底压力筛查桌面端
- Milestone: `P2：一键筛查`
- Status: `Done` on 2026-07-31 after fresh automated and visual closeout.

## Delivered scope

The PySide6 operator shell implements P-01 through P-11, preserves the existing workflow/port boundaries, and has no direct database, serial, HTTP, or file-handle access. Its child issues cover the design system, read-model demo, onboarding, reporting, acquisition, preflight, records/support, and visual regression.

## Verification

```bash
UV_OFFLINE=1 UV_CACHE_DIR=/private/tmp/feetforceplate-uv-cache \
FEETFORCEPLATE_VENV=/private/tmp/feetforceplate-p2-venv \
QT_QPA_PLATFORM=offscreen ./scripts/local-env.sh python -m pytest -q client/tests
```

The run is recorded in `/private/tmp/feetforceplate-p2-client-tests-after-workbench-header.xml`; it is a temporary, local-only test report. Visual captures for all 15 P-01–P-11 states are produced by `scripts/capture_ui_design.py` outside the repository.

## Boundary

Qt offscreen checks and visual review do not replace Windows high-DPI, physical printer, real-device, or non-technical operator acceptance. Those capabilities are outside RAY-104's explicitly local UI scope and remain tracked by the corresponding production/integration issues.

## Commit

Implementation and evidence: `aa9162f` — `Add institution access entry UI`.

## 2026-07-31 hardware-independent closeout

RAY-104's stated scope is the local PySide6 UI implementation and explicitly excludes real device, persistent storage, sync and cloud adapters. The eight child tasks RAY-105 through RAY-112 have been revalidated against that scope with current code.

- Fresh full client regression: `204 passed in 36.05s`; JUnit SHA-256 `1cff8bad710862943c8a61f17efce31425d54058a38233fd0a8e34525edb44b5`.
- Fresh full project regression: `592 passed, 3 warnings, 9 subtests passed in 40.44s`; JUnit SHA-256 `41e1e0dce034e778555ea22c4967b7ca716591e3d60e50425a04b6f84bd098ad`.
- 15 deterministic P-01–P-11 states were generated at both 1440×900 and 1280×720 (30 PNG files). Required representative pages were visually reviewed at both sizes with no primary-action obstruction or ordinary-UI technical leakage.
- Hardware, package, production adapters, printer and onsite acceptance remain visible under their own Linear issues. This closeout does not claim those capabilities.
