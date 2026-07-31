# RAY-104 Evidence

- Issue: `RAY-104` UI Design 实施：机构端足底压力筛查桌面端
- Milestone: `P2：一键筛查`
- Status: `In Review` after the implementation and automated evidence below.

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

Qt offscreen checks and visual review do not replace Windows high-DPI, physical printer, real-device, or non-technical operator acceptance. Keep the parent and child issues `In Review` until those checks are completed.

