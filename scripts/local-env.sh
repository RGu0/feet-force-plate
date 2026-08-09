#!/usr/bin/env bash
# Backward-compatible forwarding wrapper. New automation uses ./dev directly.
set -euo pipefail
project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ "$#" -eq 0 ]; then
    exec "$project_root/dev" setup
fi
exec "$project_root/dev" run "$@"
