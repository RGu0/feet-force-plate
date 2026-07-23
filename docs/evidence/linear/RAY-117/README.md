# RAY-117 evidence index

## Status

The issue remains in review. Automated contract tests and local known-weight
captures are evidence only; cross-device, repeatability, temperature/drift and
human physical-force validation remain open.

## Evidence

- `issue-snapshot.json`: Linear state captured when work began.
- `temporal-denoising-known-load-experiment-2026-07-22.md`: held-out comparison
  of stable-frame median and temporal mean denoising.
- `curve-and-processing-benchmark-2026-07-22.md`: leave-one-load-out comparison
  of monotonic response curves, free `V0` fitting and activity/background
  processing variants.
- `unified-fit-method-and-result-2026-07-22.md`: the selected one-curve A+B
  calibration candidate, its parameter values, and independent human replay.
- `unified-fit-validation-2026-07-22.png`: the corresponding mass, pressure and
  point-response visualization for A, B and human replay conditions.
- `known-weight-calibration-test-record-2026-07-22.md`: DP-P4864 conditions,
  processing method, limits and future calibration procedure for the two
  known-weight capture groups.
- `known-weight-calibration-sha256-2026-07-22.txt`: integrity manifest for the
  14 selected raw frames. The verified external archive is under
  `Device/DP-P4864/Calibration/2026-07-22-known-weight-calibration/`.

## Result boundary

The selected first-version device profile is
`do-p4864-voltage-force/provisional-unified-known-weight-v1-20260722`, using
`voltage-to-force/two-slope-monotonic/1`. Known-weight reconstruction is still
a provisional hardware calibration experiment. It must not be represented as a
verified physical-force conversion for people or as clinical acceptance.
