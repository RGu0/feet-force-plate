# UI Design QA — Steady Health Desktop

## Scope and visual truth

- Implemented flow: P-01 through P-11 in `docs/ui-desgin/FeetForcePlate UI Set.dc.html`.
- Reference states: source captures in `/private/tmp/feetforceplate-ui-reference/`.
- Implementation states: deterministic native Qt captures in `/private/tmp/feetforceplate-ui-captures/`.
- Review viewport: 1440 × 900.  The same application also has a 1280 × 720 minimum-size regression test.
- Deterministic capture command:

  ```sh
  QT_QPA_PLATFORM=offscreen ./scripts/local-env.sh python scripts/capture_ui_design.py
  ```

## Compared states

| Page | Reference | Implementation | State exercised |
| --- | --- | --- | --- |
| P-01 工作台 | `P-01-workbench.png` | `P-01-workbench.png` | recent records and primary screening CTA |
| P-03 建档 | `P-03-profile.png` | `P-03-profile.png` | institution lookup, profile form and non-blocking validation |
| P-06 站位 | `P-06-position.png` | `P-06-position.png` | dual-foot position illustration and guarded start |
| P-07 检测中 | `P-07-acquiring.png` | `P-07-acquiring.png` | latest display frame, COP and 18-second countdown |
| P-08 结果 | `P-08-result.png` | `P-08-result.png` | basic report ready and retryable processing states |
| P-10 报告 | `P-10-report.png` | `P-10-report.png` | pinned `report_id + version` document preview |

Combined comparison evidence from the visual review is retained in `/private/tmp/feetforceplate-ui-reference/comparison-P-01.png`, `comparison-p03-final2.png`, `comparison-p06-final2.png`, `comparison-p07-final.png`, `comparison-p08.png`, and `comparison-p10.png`.

## Final findings

| Surface | Result | Evidence / decision |
| --- | --- | --- |
| Layout and spacing | Pass | Replaced the prior generic sidebar shell with the design's 64px top bar, horizontal navigation, page max widths, flat surfaces and page-specific vertical rhythm. |
| Typography and colour | Pass | The shared stylesheet uses the source's calm light medical-blue token family, contrast states and border treatments. Native Qt font rasterisation remains slightly different from browser rendering. |
| Assets and icons | Pass | The source logo and the result-status SVG assets are used directly. The pressure surface is a real `DisplayFrame` visualisation; its annotation and pressure legend follow the source chart treatment. |
| Interaction and states | Pass | Page navigation, workflow guards, conflict state, non-blocking validation, consent split, device preflight recovery, stop confirmation, report states, filters and support actions are reachable in the local demo. |
| Accessibility | Pass | Controls have accessible names, keyboard focus styling and practical minimum button heights; the regression suite covers Tab order and core page affordances. |
| Viewport resilience | Pass | Automated coverage asserts the 1280 × 720 minimum usable layout; captures verify the 1440 × 900 baseline. |

## Intentional implementation decisions

- P-07 is data-driven rather than a static pressure illustration: it preserves RAY-84's latest-display-frame boundary while matching the source's grid, chart label, legend, COP and two-column hierarchy.
- P-10 renders the actual `BasicReportDocument` instead of the design mock's placeholder lines, so report content and its pinned version cannot visually drift from the active document.
- The design mock shows consent preselected, but the implemented required-consent checkbox starts unchecked to preserve the product rule and prevent unintended authorisation.

## Iteration log

1. **P1/P2 — shell and hierarchy drift:** the former generic card/sidebar presentation did not match the supplied UI Design.  Fixed in `client/app/design_system.py` and `client/app/qt_shell.py` with the source-led shell and page layouts.
2. **P2 — workbench/profile/stance density drift:** corrected content width, record-table density, form alignment and position-guide proportions; recaptured P-01/P-03/P-06.
3. **P2 — acquiring chart annotation missing:** added the source chart label and low-to-high pressure legend to `HeatmapWidget`; recaptured P-07.

No open P0, P1 or P2 visual-fidelity finding remains. Residual P3 differences are limited to platform-native font antialiasing and live pressure interpolation, both intentional consequences of a native, data-driven PySide6 client.

## Final result

**passed**
