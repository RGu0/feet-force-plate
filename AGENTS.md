## Project runtime instructions

The container-level governance instructions are authoritative for Linear,
GitHub, Worktree, evidence, and completion flow. This file records only the
project-specific runtime contract.

- Use `./dev {setup|test|lint|build}` on macOS/Linux and
  `pwsh -File dev.ps1 {setup|test|lint|build}` on Windows. For an explicit
  project command, use `./dev run <command...>` or `dev.ps1 run <command...>`.
- Do not call system Python, pip, pytest, or a shared Conda environment.
- `uv` is a device bootstrap prerequisite. Entrypoints use the committed lock
  file and opt into cache-backed centralized project environments. If that uv
  preview is unavailable, the fallback is an isolated ignored `.venv` in the
  current Worktree; never share or cloud-sync either form.
- Do not set `UV_PROJECT_ENVIRONMENT`: an explicit path bypasses uv's central
  environment behavior and can accidentally share a mutable environment.
- When dependencies change, update `pyproject.toml`, regenerate and review
  `uv.lock`, then use the project entrypoint to validate the changed lock.
