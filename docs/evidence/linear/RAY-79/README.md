# RAY-79 Evidence - 工程基础设施与分层骨架

- URL: https://linear.app/ray-app/issue/RAY-79/工程基础设施与分层骨架
- Captured at: 2026-07-30T03:42:44Z
- Snapshot: In Review; P1：可靠采集; High

## Acceptance snapshot

- [x] client/cloud/shared layered skeleton
- [x] Python 3.11+ lock, ruff, mypy, pytest, pre-commit
- [x] Windows delivery and macOS development compatibility
- [x] CI for protocol, recovery, upload, and algorithm regression
- [x] configuration/key separation, redacted structured logs, versioned builds

## Implementation and decisions

### Layered code boundary

- Client responsibilities are separated into `client/workflow`, `client/device`,
  `client/spool`, `client/local_analysis`, `client/reporting`, and the terminal
  composition/security layers under `client/app` and `client/security`.
- Cloud responsibilities are independently rooted at `cloud/ingestion`,
  `cloud/analysis`, `cloud/reporting`, `cloud/device_management`, and
  `cloud/observability`.
- Cross-process contracts live in `shared/contracts`; schema versions and
  stable error codes are enforced in the contracts and `cloud/api/errors.py`.

This is the implemented equivalent of the module map in
`docs/架构设计文档.md` §16–18. Existing package names intentionally remain
stable; RAY-79 does not rename working acquisition, recovery, or cloud modules.

### Developer and delivery infrastructure

- `pyproject.toml` requires Python 3.11+, pins development quality-tool ranges,
  and defines pytest, ruff, and mypy gates; `uv.lock` resolves them.
- `.pre-commit-config.yaml` checks YAML/JSON/trailing whitespace, runs ruff, and
  runs the configured mypy boundary through the project environment.
- `scripts/local-env.sh` and `scripts/local-env.ps1` keep `uv` virtual
  environments outside OneDrive for macOS/Linux and Windows respectively.
- `.github/workflows/quality.yml` runs the locked environment on Windows,
  macOS, and Linux. It covers protocol fixtures, segment recovery, cloud-upload
  contracts, analysis orchestration, and safe telemetry events.
- `client/app/packaging/build-config.json` and `client/app/deployment.py`
  retain the Windows-first packaging contract while preserving a macOS pilot.

### Security, observability, and provenance

- `client/security/key_envelope.py` keeps terminal private keys in the system
  keyring and uses envelope encryption; no terminal secret is stored in build
  metadata.
- `cloud/observability/events.py` allowlists structured safe-context fields and
  rejects identity, credential, raw-payload, report, and stack-trace values.
- `client/app/deployment.py:BuildManifest` records application, protocol,
  report-schema, data-schema, compatibility, commit, target, and timestamp
  fields for build provenance.

### Static-quality scope

`ruff` blocks Python correctness findings across the repository. `mypy` blocks
the versioned `shared/contracts` and privacy-critical `cloud/observability`
boundary. The broader Qt presentation and numerical pipeline type debt is
explicitly excluded from this foundation gate pending a separately reviewed
typing remediation; it is not hidden by a blanket ignore.

## Verification

Executed on macOS with Python 3.11.15 from the project wrapper:

```text
QT_QPA_PLATFORM=offscreen ./scripts/local-env.sh ruff check .
# All checks passed

QT_QPA_PLATFORM=offscreen ./scripts/local-env.sh mypy
# Success: no issues found in 10 source files

QT_QPA_PLATFORM=offscreen ./scripts/local-env.sh python -m pytest \
  --junitxml=docs/evidence/linear/RAY-79/pytest-foundation-regression.xml \
  client/tests/test_ray_91_protocol.py \
  client/tests/test_ray_91_reference_protocol_fixture.py \
  tests/spool/test_recovery.py tests/spool/test_valid_session_commit.py \
  cloud/tests/test_client_sync_contract.py cloud/tests/test_segment_ingestion.py \
  tests/cloud/analysis/test_orchestrator.py \
  tests/cloud/observability/test_events.py
# 62 passed, 1 collection warning
```

The JUnit result is committed with this evidence. The only warning is pytest
mistaking the Pydantic `TestProtocol` contract class for a test class; it does
not affect collection or assertions.

## Boundary, failures, and limits

The local checks do not execute GitHub Actions or validate a real Windows
installer, CH340 driver, signing/notarization, or a production secret store.
Those target-environment checks remain the reason for the Linear state **In
Review**. This evidence makes no hardware, calibration, clinical, or production
deployment claim.

## Windows acceptance update (2026-08-03)

The foundation gate was re-run on Windows with the project wrapper and CPython
3.11.15. The recovery path exposed POSIX-only directory `fsync` calls, and the
file-system telemetry repository exposed an unconditional `os.fchmod` call;
both prevent the declared Windows delivery target from exercising the
foundation workflow. The implementation now preserves the flushed-file and
atomic-rename behavior on Windows, where Python cannot open a directory for
`fsync`, and falls back to `chmod` when `fchmod` is unavailable.

Fresh verification completed successfully:

```text
powershell -ExecutionPolicy Bypass -File .\scripts\local-env.ps1 ruff check .
# All checks passed!

powershell -ExecutionPolicy Bypass -File .\scripts\local-env.ps1 mypy shared/contracts cloud/observability
# Success: no issues found in 13 source files

powershell -ExecutionPolicy Bypass -File .\scripts\local-env.ps1 python -m pytest ...
# 66 passed, 1 existing TestProtocol collection warning

powershell -ExecutionPolicy Bypass -File .\scripts\local-env.ps1 uv lock --check
git diff --check
# both passed
```

The pytest selection contains the configured RAY-79 protocol, recovery, sync,
ingestion, analysis, and safe-telemetry regressions, plus the persistent
validation-telemetry API regression that exercises the Windows fallback.
POSIX mode-bit assertions are intentionally limited to POSIX: Windows `chmod`
does not model a private DACL. Terminal key material remains outside this store
and uses the system keyring/envelope boundary. Windows ACL hardening for
non-key diagnostic files is a separate security follow-up, not a claim of this
foundation acceptance.

## Commit

Recorded with the RAY-79 infrastructure commit history.
