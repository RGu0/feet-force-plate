# RAY-111 Evidence

- Issue: `RAY-111` 检测准备与站位引导（P-05～P-06）
- Milestone: `P2：一键筛查`
- Status: `Done` on 2026-07-31.

## Delivered scope

- P-05 presents device, storage, calibration, sync, and zero-load checks as plain-language status cards with a single recoverable action.
- P-06 presents a low-detail bilateral foot-placement guide, text and numeric countdown, departure reset, and guarded manual start.
- Technical details stay outside the ordinary operator view.

## Verification

`client/tests/test_ray_91_qt.py`, `test_ray_91_position_guidance.py`, `test_ray_101_qt_shell.py`, and startup-gate UI tests pass in the P2 regression. Both success/failure P-05 and P-06 were rendered and visually reviewed offscreen.

## Boundary

Real baseline/connection inputs and Windows/onsite operation remain separate hardware and field validations.

## Commit

Implementation and evidence: `aa9162f` — `Add institution access entry UI`.

## 2026-07-31 hardware-independent closeout

- Fresh full client regression: `204 passed in 36.05s`; full project regression: `592 passed, 3 warnings, 9 subtests passed in 40.44s`.
- Fresh P-05 pass/fail and P-06 captures were generated at 1440×900 and 1280×720. Manual review confirmed plain-language recovery, four-stage provenance, visible position/countdown text and an unobscured guarded start action.
- Real connection/baseline inputs remain startup/device integration evidence under RAY-114/RAY-115. RAY-111's local UI/state-contract acceptance is complete without treating replay as physical input.
