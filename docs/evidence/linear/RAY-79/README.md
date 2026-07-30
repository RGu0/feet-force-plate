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

### 2026-07-30 quality-gate scope

The repository already contains the required `client/`, `cloud/`, and `shared/`
layer boundaries. This issue's remaining implementation work is deliberately
limited to reproducible Python quality tooling:

- locked development dependencies and project-local configuration for Ruff, mypy,
  pytest, and pre-commit;
- a CI workflow that runs protocol/device, local recovery, hardware-standardization,
  cloud contract, and algorithm regression tests;
- type checking initially limited to the P1 transport/parser contract, avoiding
  a claim that unfinished spool, UI, deployment, or cloud integrations are type-clean.

The workflow never supplies secrets and does not exercise a physical serial device,
  operating-system credential store, or external cloud service.

## Verification

Automated on 2026-07-30 through the repository's external-venv wrapper:

| Command | Result |
| --- | --- |
| `bash scripts/local-env.sh ruff check client/device client/spool client/hardware_standardization shared/contracts tests/device tests/spool tests/hardware_standardization` | PASS |
| `bash scripts/local-env.sh mypy` | PASS — transport/parser contract (3 source files) |
| `bash scripts/local-env.sh pre-commit run --all-files` | PASS — scoped Ruff hook |
| `bash scripts/local-env.sh python -m pytest tests/device tests/spool tests/hardware_standardization cloud/tests -q` | PASS — 227 passed; 3 pre-existing Pytest collection warnings for Pydantic `TestProtocol` |
| `git diff --check` | PASS |

`uv.lock` was regenerated after adding the development tools. The CI workflow
uses `uv sync --extra dev --locked`, then runs the same lint/type/test quality
gates without a repository-local virtual environment.

## Boundary, failures, and limits

This task cannot claim the full issue complete because its global skeleton acceptance exceeds the delegated ownership boundary.

The new CI workflow is a checked-in configuration; it has not yet executed on
GitHub Actions. The current type-check gate is intentionally limited to the
transport/parser contract; existing spool and standardization modules still
need incremental typing work before a repository-wide mypy claim is valid.
Cross-platform Windows validation, real Keychain/Credential Vault behavior,
physical serial acquisition, cloud deployment credentials, and production
secret management remain outside this automatic engineering-gate evidence.

## Commit

Pending commit for this quality-gate follow-up.
