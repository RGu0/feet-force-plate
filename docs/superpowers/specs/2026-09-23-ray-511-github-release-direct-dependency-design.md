# RAY-511: GitHub Release direct dependency design

## Purpose

A fresh FeetForcePlate worktree must install the approved Foundation release through the governed `setup` command without first copying or downloading a wheel into that worktree. The dependency must remain pinned to a specific release artifact and SHA-256. This supersedes the local artifact bootstrap delivered by RAY-389 while preserving that issue as historical evidence.

Linear RAY-511 revision R2 is the authoritative requirement. The registered delivery scope is `private-registry-consumer`; its name is immutable even though the confirmed distribution source is the existing public GitHub Release rather than a Python package registry.

## Distribution and lock

Keep `techflex-cloud-foundation==0.2.0` in `project.dependencies`. Replace the path source in `[tool.uv.sources]` with the exact wheel URL:

`https://github.com/RGu0/techflex-cloud-foundation/releases/download/v0.2.0/techflex_cloud_foundation-0.2.0-py3-none-any.whl`

Regenerate `uv.lock` using the repository's pinned uv workflow. The Foundation package entry must identify the URL source, version `0.2.0`, and wheel hash `sha256:1dd34fb4902fb7359af346e153123e8db12befc6ae8a9de2105e11f80af74303`, matching the published Release. Do not hand-author a lock entry or accept an unrelated package source. A mismatched downloaded artifact must fail installation.

The Release is public as of this design. No GitHub token is required for its download. If access policy changes later, that is a new requirement because direct URL authentication differs from the current `gh release download` step.

## Governed entrypoints and CI

On macOS/Linux, `dev` keeps its locked `uv sync` and `uv run` behavior and centralized environment policy. Remove the Python artifact preparation call and `--find-links .foundation-artifacts`. On Windows, `dev.ps1` keeps uv managed Python installation and its locked sync/run behavior; remove the separate managed Python execution of the artifact preparation script. `setup` has no extra download stage. All four governed actions (`setup`, `test`, `lint`, `build`) retain the manifest entrypoint contract and fail with uv's actual error when the Release cannot be reached or the locked wheel hash differs.

GitHub Actions uses the committed URL and lock for `uv sync --locked`. Remove the dedicated release token and download step. Keep the Windows clean managed Python bootstrap job and the existing quality gates. No wheel, credential, or environment is committed or cloud-synced.

Remove the obsolete `scripts/prepare_foundation_artifact.py`, `foundation-artifact.lock.json`, and their download-specific tests after replacing the relevant regression coverage. Remove the stale `.foundation-artifacts/` ignore entry only if no longer referenced.

## Verification

Contract tests inspect the committed project and lock data, asserting the exact URL, version, and SHA-256 and the absence of a local path source. Entrypoint tests assert that clean setup reaches locked sync without an artifact preparation step on both Unix and Windows; the Windows test still verifies that no global Python command is needed. CI runs these contracts on its operating-system matrix.

After regenerating the lock, run the scope's governed `setup`, `test`, `lint`, and `build` commands. Record actual command results and any environmental failure in the scope evidence directory. A clean worktree with no `.foundation-artifacts/` must be sufficient. Review the resulting lock diff for unrelated index or package changes before accepting it. GitHub PR review and validation follow the registered scope workflow; merge and Linear completion require their separate gates.

## Documentation

Update the project runtime instructions, README, architecture and communication documents, and Windows release guides where they currently describe the local wheel, separate artifact lock, private repository authentication, or manual download. They should point to `pyproject.toml` and `uv.lock` as the dependency source and integrity record. Preserve the rule that application code consumes Foundation's public API rather than duplicating it.

## Failure boundaries

- Missing uv, a broken governed topology, an invalid or stale lock, an unavailable GitHub Release, and a hash mismatch stop the relevant command with its specific cause.
- Local caches may speed up installation but are never required as a source of truth. A fresh worktree must not depend on an artifact in another worktree.
- The existing bootstrap-aware governance preflight still skips lock checking for `setup` only; `test`, `lint`, and `build` continue to check the lock before running the entrypoint.
