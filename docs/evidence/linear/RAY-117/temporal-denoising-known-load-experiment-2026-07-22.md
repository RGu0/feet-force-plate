# RAY-117 temporal denoising known-load experiment

## Scope

This experiment evaluates only the two local known-weight capture groups. It
does not use human mass reconstruction and does not modify serial parsing or
the immutable raw capture files.

For each variant, `alpha` and `beta` were fitted from fixed training load
levels. Error is reported only for the remaining held-out weights. The spatial
method was unchanged: point force, 6 mm circular point area, bilinear pressure
interpolation, then coordinate-area integration.

## Results

| Capture group | Existing stable-frame median | Mean only | 5-frame centred mean + mean | 11-frame centred mean + mean |
| --- | ---: | ---: | ---: | ---: |
| Original contact | 1.643% | 2.021% | 2.021% | 2.019% |
| Small contact | 2.855% | 2.886% | 2.876% | 2.883% |

Values are held-out mean absolute percentage error.

## Decision

The existing per-cell median after stable-frame selection is retained. The
tested mean filters do not reduce error materially and are slightly worse on
both groups. Temporal filtering cannot remove a sensor point's persistent
zero-offset or gain difference; that needs a separately evidenced per-point
calibration procedure. The force conversion remains provisional.
