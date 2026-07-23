# RAY-86 Evidence - 可靠采集监控与 P1 验收

- URL: https://linear.app/ray-app/issue/RAY-86/可靠采集监控与-p1-验收
- Captured at: 2026-07-20T08:57:11Z
- Snapshot: Backlog; P1：可靠采集; Urgent

## Acceptance snapshot

- [ ] internal Hz/gap/CheckSum/resync/queue/disk metrics
- [ ] stable errors and structured logs
- [ ] physical 30-minute run without client-side silent loss, UI freeze, or sustained leak
- [ ] unplug -> INCOMPLETE with sealed-segment recovery
- [ ] network loss does not block acquisition/basic report
- [ ] crash/power/disk fault states are explainable and never false-success
- [ ] invalid-quality sessions cannot produce a client report

## Implementation and decisions

Planned after acquisition and spool. Automated/simulator tooling will report its evidence class explicitly.

## Verification

Not started.

## Boundary, failures, and limits

The physical 30-minute and manual/UI checks cannot be marked complete without real evidence.

## Commit

Pending.
