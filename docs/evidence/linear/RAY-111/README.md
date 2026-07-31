# RAY-111 Evidence

- Issue: `RAY-111` 检测准备与站位引导（P-05～P-06）
- Milestone: `P2：一键筛查`
- Status: `In Review`

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
