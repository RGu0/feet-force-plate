# RAY-546 Windows resilience acceptance

## Scope

- Linear issue: [RAY-546](https://linear.app/ruiguo/issue/RAY-546/windows-打包客户端断网慢网与容量边界验收)
- Delivery scope: `windows-resilience-acceptance`
- Requirement revision: `R1`
- Branch: `linear/ray-546/windows-resilience-acceptance`
- Synthetic data only; no four-stage human collection is part of this scope.

## Evidence recorded on 2026-09-30

The governed Windows test action completed on Windows 10 x86_64 with CPython 3.11.15 and Foundation 0.2.0 from the committed lock: **1,322 passed, 31 skipped, 6 warnings**. It included the SQLite boundary tests for the exact 24-hour, 50-session, and 2 GiB thresholds, the packaged upload runtime recovery tests, and the `LOCAL_BASIC_COPY` restart/idempotency tests. The test command took 165.76 seconds.

The source boundary tests use the real `StateStore` SQLite schema and synthetic sealed-segment records. Their clock is controlled: exactly 24 hours remains eligible, and one nanosecond later blocks a new test. The 50th nonconfirmed handoff and exactly 2 GiB of accounted pending segment bytes block only new tests; current-session finalization, report viewing, and upload remain allowed. The fixture files stay small while SQLite stores boundary byte counts, so this does not claim a physical 2 GiB disk pressure run or an elapsed 24-hour soak. These tests exercise the client source components, not their combined behavior in the packaged executable.

An unsigned development Windows x86_64 package was built and passed `verify-portable-release.ps1`:

- Source commit: `94d0610d920e377d036061177519541bbe30c71e` (the scope's starting commit, `origin/master`).
- Package: `FeetForcePlate-0.1.0-windows-x86_64.zip`
- SHA-256: `395638afbf18c8bc6ad1a60692d59f95927fdf81ca1024a3f211589a9534fe41`
- Local package: `.local-artifacts/ray546-windows-client-build-20260930/release/`
- Signing status: `unsigned-development`; internal validation only.

## Acceptance still open

The packaged executable was not launched. An isolated-profile, offscreen startup smoke was attempted, but the automatic approval review rejected the process launch/termination command with `blocked by policy`. No alternate process-control path was used. Package build and manifest verification do not establish GUI startup or packaged fault behavior.

The following have not been accepted against the packaged EXE:

- Public-network disconnect, restoration, and client restart with raw-segment persistence and idempotent `LOCAL_BASIC_COPY` delivery.
- Controlled slow-network acquisition and local basic-report timing.
- The 24-hour, 50-pending-session, and 2 GiB combination through the packaged client's SQLite, startup gate, and background worker.

The Linear description does not state numeric latency limits for slow-network acquisition or local report generation. Record observed timings in the controlled run and confirm the pass limits with the requirement owner before calling that criterion passed.

## Required controlled environment

- An isolated nonproduction API/tenant seeded only with synthetic records, plus test-only account/license inputs, the API base URL, CA bundle, and public license key. Do not use participant data or production credentials.
- The local controlled fault lab enabled with its isolated PostgreSQL admin, tenant, and platform DSNs. The Windows suite reported that this lab and the isolated live PostgreSQL DSNs were not configured on this machine.
- An approved interactive Windows session or automation path to launch the unsigned package with an isolated application-data directory and to control the client restart. The current automatic review rejected that process action.
- A synthetic serial source/virtual COM pair for the slow-network collection case; no physical device or human collection is required.

Use the RAY-546 evidence directory for the next run's sanitized screenshots/log summaries, package hash, SQLite aggregate counts, retry/idempotency receipts, and measured timings. Do not store tokens, license material, identifiers, or raw session payloads in the evidence.
