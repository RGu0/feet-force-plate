# RAY-86 Evidence - 可靠采集监控与 P1 验收

- URL: https://linear.app/ray-app/issue/RAY-86/可靠采集监控与-p1-验收
- Captured at: 2026-07-23T04:54:28Z
- Snapshot: In Progress; P1：可靠采集; Urgent

## Acceptance snapshot

- [x] Host gap, parser integrity/resync, queue timeout, storage failure and disconnect all produce `INVALID` and delete the active staging directory.
- [x] Automated quality gate covers no bad point, one/two isolated repaired bad points, adjacent clusters, edge cells, excess baseline-noisy cells and saturation/conversion failure.
- [x] `INVALID` capture has no formal SQLite session, network handoff, derived artifact or report/algorithm input.
- [x] CheckSum remains observe-only for the observed compact profile; no device-side sequence/timestamp claim is made.
- [ ] Real 10-minute continuous run through baseline → preprocessing → valid commit → startup recovery → export.
- [ ] Actual cable removal, disk-full, power interruption, OS secure-storage and operator re-test workflow.

## Implementation and decisions

The acceptance composition is `HardwareSessionRuntime`: `ByteTransport → incremental parser →
encrypted staging → hardware quality gate → formal valid session`. Quality policy and baseline/
force provenance are recorded in the encrypted derived artifact. The parser's source index and
timestamps are host-generated; the hardware does not provide device sequence or clock data.

## Verification

Automated command run on 2026-07-23:

```text
./scripts/local-env.sh python -m pytest tests/device tests/spool tests/hardware_standardization -q
```

Result: **105 passed**. `git diff --check` also passed.

Existing real-device evidence under `docs/evidence/linear/RAY-78/` proves an observed 10-minute
raw structural capture at about 20.6 Hz, but it predates this validity-gated runtime and therefore
is not P1 end-to-end acceptance evidence.

## Boundary, failures, and limits

The required real 10-minute and manual/operator checks cannot be marked complete without new
evidence. The earlier 30-minute requirement has been superseded by the confirmed 10-minute P1
acceptance, but neither duration authorizes a Done state until the current runtime is exercised.

## Commit

Automated acceptance evidence commit: pending.
