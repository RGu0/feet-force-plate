#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 1 ]; then
    echo "usage: $0 /absolute/path/to/integration.env" >&2
    exit 2
fi

env_file="$1"
if [ ! -r "$env_file" ]; then
    echo "integration environment file is not readable" >&2
    exit 2
fi

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
set -a
# shellcheck disable=SC1090
source "$env_file"
set +a

: "${FFP_INTEGRATION_PYTHON:?missing FFP_INTEGRATION_PYTHON}"
: "${FFP_INTEGRATION_TLS_CERT:?missing FFP_INTEGRATION_TLS_CERT}"
: "${FFP_INTEGRATION_TLS_KEY:?missing FFP_INTEGRATION_TLS_KEY}"

cd "$project_root"
export PYTHONPATH="$project_root${PYTHONPATH:+:$PYTHONPATH}"
exec "$FFP_INTEGRATION_PYTHON" -m uvicorn \
    cloud.api.integration:app_from_environment \
    --factory \
    --host "${FFP_INTEGRATION_HOST:-0.0.0.0}" \
    --port "${FFP_INTEGRATION_PORT:-7443}" \
    --ssl-certfile "$FFP_INTEGRATION_TLS_CERT" \
    --ssl-keyfile "$FFP_INTEGRATION_TLS_KEY" \
    --no-access-log
