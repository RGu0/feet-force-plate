#!/usr/bin/env bash
# Run FeetForcePlate with a per-machine virtual environment outside OneDrive.
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
uv_bin="${UV_BIN:-}"

if [ -z "$uv_bin" ]; then
    uv_bin="$(command -v uv 2>/dev/null || true)"
fi
if [ -z "$uv_bin" ] && [ -x "$HOME/.local/bin/uv" ]; then
    uv_bin="$HOME/.local/bin/uv"
fi

if [ -z "$uv_bin" ] || [ ! -x "$uv_bin" ]; then
    echo "uv 未安装。请先在本机安装 uv，再重新运行本脚本。" >&2
    exit 127
fi

cache_root="${XDG_CACHE_HOME:-$HOME/.cache}/feetforceplate"
export UV_PROJECT_ENVIRONMENT="${FEETFORCEPLATE_VENV:-$cache_root/venv}"
export PYTHONPATH="$project_root${PYTHONPATH:+:$PYTHONPATH}"

cd "$project_root"
"$uv_bin" sync --extra dev --locked

if [ "$#" -gt 0 ]; then
    exec "$uv_bin" run --extra dev "$@"
fi
