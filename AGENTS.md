## Project runtime instructions

The container-level governance instructions are authoritative for Linear,
GitHub, Worktree, evidence, and completion flow. This file records only the
project-specific runtime contract.

- Use `./dev {setup|test|lint|build}` on macOS/Linux and
  `pwsh -File dev.ps1 {setup|test|lint|build}` on Windows. For an explicit
  project command, use `./dev run <command...>` or `dev.ps1 run <command...>`.
- Do not call system Python, pip, pytest, or a shared Conda environment.
- `techflex-cloud-foundation` is pinned by version and public GitHub Release
  URL in `pyproject.toml`; `uv.lock` pins its wheel SHA-256. Entrypoints use
  locked uv sync, which downloads and verifies the wheel without a worktree-local
  artifact or release credential. `setup` also caches the published 0.9.4
  sdist with its pinned SHA-256 under ignored `.foundation-source/`; tests
  require the verified cache offline. Never install an unverified wheel or bypass
  the committed lock. This cache and locator are developer-only; setup must
  prewarm dependencies and source. Tests and lookups never download source;
  offline wrapper sync fails closed when dependencies are missing.
- Shared contracts, generic server, schema/migrations, smoke and deployment
  tooling belong to the pinned foundation release. Keep product integration and
  desktop behavior here; do not recreate deleted shared/server copies. Resolve
  the verified release source offline with
  `UV_OFFLINE=1 ./dev run python scripts/foundation_release_source.py --offline --print-root`
  (Windows: set `$env:UV_OFFLINE="1"` for this invocation, then use
  `pwsh -File dev.ps1 run python scripts/foundation_release_source.py --offline --print-root`;
  restore the prior environment value afterward). Follow
  that source tree's documentation for its tools; do not invoke deleted local
  script paths. The lookup fails closed for missing or modified cache content.
- Adoption does not authorize deployment, parent desktop activation, real upload
  or device acceptance. Keep those user gates and evidence separate.
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
