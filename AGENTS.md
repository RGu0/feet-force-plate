## Imported Claude Cowork project instructions

## Python / UV environment

- This repository uses `uv` as its default Python environment and dependency runner.
- Project environments must stay outside the OneDrive workspace. Do not create,
  reuse, or modify a repository-local `.venv`.
- On macOS/Linux, initialize or reconcile the per-machine environment with
  `./scripts/local-env.sh`. On Windows, use
  `powershell -ExecutionPolicy Bypass -File .\scripts\local-env.ps1`.
- Run Python, tests, and project scripts through the same wrapper; do not call a
  system `python`, `pip`, or `pytest` directly. For example:
  - macOS/Linux: `./scripts/local-env.sh python -m pytest`
  - macOS/Linux: `./scripts/local-env.sh python main.py`
  - Windows: `powershell -ExecutionPolicy Bypass -File .\scripts\local-env.ps1 python -m pytest`
  - Windows: `powershell -ExecutionPolicy Bypass -File .\scripts\local-env.ps1 python main.py`
- Do not require manual virtual-environment activation. The wrappers set
  `UV_PROJECT_ENVIRONMENT` to a per-machine cache directory outside OneDrive and
  then invoke `uv sync` / `uv run`.
- When changing dependencies, update `pyproject.toml`, run `uv lock`, then
  rerun the platform wrapper and commit the resulting `uv.lock` change.
