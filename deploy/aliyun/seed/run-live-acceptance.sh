#!/usr/bin/env bash
set -euo pipefail
umask 077

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
    echo "run-live-acceptance.sh must run as root" >&2
    exit 2
fi
if [[ "$#" -ne 2 || ! -f "$1" ]]; then
    echo "usage: run-live-acceptance.sh CA_CERT REDACTED_OUTPUT" >&2
    exit 2
fi

ca_cert="$1"
redacted_output="$2"
service_user="feetforceplate"
app_root="/opt/feetforceplate/app"
acceptance_root="/var/lib/feetforceplate/acceptance"
state_file="$acceptance_root/private-state.json"
evidence_file="$acceptance_root/aliyun-seed-summary.json"
junit_file="$acceptance_root/postgres-role-parity.xml"
env_file="/etc/feetforceplate/seed.env"

install -d -o "$service_user" -g "$service_user" -m 0700 "$acceptance_root"
cleanup() {
    rm -f -- "$state_file"
}
trap cleanup EXIT

run_seed_python() {
    local phase="$1"
    runuser -u "$service_user" -- bash -c '
        set -euo pipefail
        cd /opt/feetforceplate/app
        export FEETFORCEPLATE_VENV=/var/lib/feetforceplate/runtime/venv
        export XDG_CACHE_HOME=/var/lib/feetforceplate/runtime/cache
        set -a
        source /etc/feetforceplate/seed.env
        set +a
        exec ./scripts/local-env.sh python scripts/verify_seed_live.py \
            --phase "$1" \
            --base-url "$FEETFORCEPLATE_PUBLIC_BASE_URL" \
            --ca-file "$2" \
            --state "$3" \
            --evidence "$4"
    ' bash "$phase" "$ca_cert" "$state_file" "$evidence_file"
}

run_seed_python before-restart
systemctl restart postgresql
systemctl restart feetforceplate-seed

source "$env_file"
public_base_url="$FEETFORCEPLATE_PUBLIC_BASE_URL"
ready=0
for _attempt in $(seq 1 30); do
    if curl --silent --show-error --fail --cacert "$ca_cert" \
        "$public_base_url/health/ready" \
        >/dev/null; then
        ready=1
        break
    fi
    sleep 1
done
if [[ "$ready" -ne 1 ]]; then
    echo "seed service did not recover after PostgreSQL and application restart" >&2
    exit 1
fi

run_seed_python after-restart
runuser -u "$service_user" -- bash -c '
    set -euo pipefail
    cd /opt/feetforceplate/app
    export FEETFORCEPLATE_VENV=/var/lib/feetforceplate/runtime/venv
    export XDG_CACHE_HOME=/var/lib/feetforceplate/runtime/cache
    set -a
    source /etc/feetforceplate/seed.env
    set +a
    export FEETFORCEPLATE_TEST_TENANT_DSN="$FEETFORCEPLATE_TENANT_DSN"
    export FEETFORCEPLATE_TEST_ACTIVATION_DSN="$FEETFORCEPLATE_ACTIVATION_DSN"
    export FEETFORCEPLATE_TEST_PLATFORM_DSN="$FEETFORCEPLATE_PLATFORM_DSN"
    exec ./scripts/local-env.sh python -m pytest \
        cloud/tests/test_postgres_access_repository.py \
        --junitxml "$1" -q
' bash "$junit_file"

runuser -u "$service_user" -- bash -c '
    export FEETFORCEPLATE_VENV=/var/lib/feetforceplate/runtime/venv
    export XDG_CACHE_HOME=/var/lib/feetforceplate/runtime/cache
    "$1" python - "$2" <<"PY"
import json
from pathlib import Path
path = Path(__import__("sys").argv[1])
value = json.loads(path.read_text())
value["postgres_role_parity_verified"] = True
path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
PY
' bash "$app_root/scripts/local-env.sh" "$evidence_file"

systemctl start feetforceplate-backup.service
install -D -o "${SUDO_USER:-root}" -g "${SUDO_USER:-root}" -m 0644 \
    "$evidence_file" "$redacted_output"
printf 'live_acceptance=passed evidence=%s postgres_junit=%s secrets=not-printed\n' \
    "$redacted_output" "$junit_file"
