# RAY-79 Evidence - 工程基础设施与分层骨架

- URL: https://linear.app/ray-app/issue/RAY-79/工程基础设施与分层骨架
- Captured at: 2026-07-20T08:57:11Z
- Snapshot: Backlog; P1：可靠采集; High

## Acceptance snapshot

- [ ] client/cloud/shared layered skeleton
- [ ] Python 3.11+ lock, ruff, mypy, pytest, pre-commit
- [ ] Windows delivery and macOS development compatibility
- [ ] CI for protocol, recovery, upload, and algorithm regression
- [ ] configuration/key separation, redacted structured logs, versioned builds

## Implementation and decisions

Planned contribution is limited to the owned `client/device`, `client/spool`, fixture, and test paths. Cloud, UI, algorithms, and other shared directories remain outside this delegated scope.

## Verification

Not started.

## Boundary, failures, and limits

This task cannot claim the full issue complete because its global skeleton acceptance exceeds the delegated ownership boundary.

## Commit

Pending.
