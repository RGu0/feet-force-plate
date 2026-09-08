## Project runtime instructions

The container-level governance instructions are authoritative for Linear,
GitHub, Worktree, evidence, and completion flow. This file records only the
project-specific runtime contract.

- Use `./dev {setup|test|lint|build}` on macOS/Linux and
  `pwsh -File dev.ps1 {setup|test|lint|build}` on Windows. For an explicit
  project command, use `./dev run <command...>` or `dev.ps1 run <command...>`.
- Do not call system Python, pip, pytest, or a shared Conda environment.
- The private `techflex-cloud-foundation` wheel is pinned by version and
  SHA-256 in `foundation-artifact.lock.json`. Every entrypoint action runs
  `scripts/prepare_foundation_artifact.py` before syncing; `setup` downloads it
  from the private `RGu0/techflex-cloud-foundation` release, so `gh` must be
  authenticated (CI uses `TECHFLEX_FOUNDATION_RELEASE_TOKEN`). Never install an
  unverified wheel or add a `[tool.uv.sources]` fallback that bypasses the lock.
- Sensitive outbound communication goes through the foundation's public API
  (`SecureTransport`, `AuthorizedTransport`, `CredentialVault`,
  `TrustBundleVerifier`). Do not re-implement transport, authorization,
  credential, trust, or operation-store behaviour in this repository.
- `uv` is a device bootstrap prerequisite. Entrypoints use the committed lock
  file and opt into cache-backed centralized project environments. If that uv
  preview is unavailable, the fallback is an isolated ignored `.venv` in the
  current Worktree; never share or cloud-sync either form.
- Do not set `UV_PROJECT_ENVIRONMENT`: an explicit path bypasses uv's central
  environment behavior and can accidentally share a mutable environment.
- When dependencies change, update `pyproject.toml`, regenerate and review
  `uv.lock`, then use the project entrypoint to validate the changed lock.
