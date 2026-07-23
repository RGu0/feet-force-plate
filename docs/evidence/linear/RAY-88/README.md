# RAY-88 Evidence - 内部回放与故障复现工具

- URL: https://linear.app/ray-app/issue/RAY-88/内部回放与故障复现工具
- Captured at: 2026-07-20T08:57:11Z
- Snapshot: Backlog; P1：可靠采集; High

## Acceptance snapshot

- [ ] read immutable encrypted segments and manifest
- [ ] reuse live RawFrame/FrameSource contract
- [ ] digest/version/timeline verification before playback
- [ ] frame-step, speed, loop, and seek
- [ ] internal visualization/quality-event integration
- [ ] disconnect/checksum/missing-segment/algorithm-failure reproduction
- [ ] redacted diagnostic export; no customer-facing debug UI

## Implementation and decisions

Planned after RAY-87 container and recovery format stabilizes.

## Verification

Not started.

## Boundary, failures, and limits

UI and cloud algorithm-failure surfaces are outside this task; the owned deliverable is the replay/source and fault-reproduction core.

## Commit

Pending.
