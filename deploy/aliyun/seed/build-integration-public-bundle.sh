#!/usr/bin/env bash
set -euo pipefail
umask 077

usage() {
    cat <<'USAGE'
Build the fixed-name public bundle used by the RAY-99 integration client.

Usage:
  sudo /opt/feetforceplate/app/deploy/aliyun/seed/build-integration-public-bundle.sh \
    --api-base-url https://<host>:7443 \
    --ca-cert /path/to/public-ca.pem \
    --license-public-key /path/to/license-public.key \
    --license-key-id license/1

Both input paths must point to already-exported public material. The operator
must not pass a private License key or the service's private env file.

Options:
  --api-base-url URL          HTTPS integration endpoint on explicit port 7443
  --ca-cert PATH              exported public CA certificate
  --license-public-key PATH   exported License verification public key
  --license-key-id ID         non-empty public License key identifier
  --replace                   preserve and replace an existing published bundle
USAGE
}

die() {
    echo "build-integration-public-bundle.sh: $*" >&2
    exit 2
}

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
    echo "build-integration-public-bundle.sh must run as root" >&2
    exit 2
fi

api_base_url=""
ca_cert=""
license_public_key=""
license_key_id=""
replace=0

while [[ "$#" -gt 0 ]]; do
    case "$1" in
        --api-base-url|--ca-cert|--license-public-key|--license-key-id)
            option="$1"
            [[ "$#" -ge 2 && -n "$2" && "$2" != --* ]] \
                || die "missing value for $option"
            case "$option" in
                --api-base-url)
                    [[ -z "$api_base_url" ]] || die "duplicate option: $option"
                    api_base_url="$2"
                    ;;
                --ca-cert)
                    [[ -z "$ca_cert" ]] || die "duplicate option: $option"
                    ca_cert="$2"
                    ;;
                --license-public-key)
                    [[ -z "$license_public_key" ]] \
                        || die "duplicate option: $option"
                    license_public_key="$2"
                    ;;
                --license-key-id)
                    [[ -z "$license_key_id" ]] || die "duplicate option: $option"
                    license_key_id="$2"
                    ;;
            esac
            shift 2
            ;;
        --replace)
            [[ "$replace" -eq 0 ]] || die "duplicate option: --replace"
            replace=1
            shift
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        --*)
            die "unknown option: $1"
            ;;
        *)
            die "positional arguments are not accepted: $1"
            ;;
    esac
done

[[ -n "$api_base_url" ]] || die "missing required option: --api-base-url"
[[ -n "$ca_cert" ]] || die "missing required option: --ca-cert"
[[ -n "$license_public_key" ]] \
    || die "missing required option: --license-public-key"
[[ -n "$license_key_id" ]] || die "missing required option: --license-key-id"

bundle_root="${FEETFORCEPLATE_PUBLIC_BUNDLE_ROOT:-/srv/feetforceplate/acceptance-public}"
[[ "$bundle_root" == /* ]] \
    || die "FEETFORCEPLATE_PUBLIC_BUNDLE_ROOT must be an absolute path"
destination="$bundle_root/ray-99-integration"

for command_name in python3 sha256sum install mv; do
    command -v "$command_name" >/dev/null 2>&1 \
        || die "required command is unavailable: $command_name"
done

if [[ -e "$destination" || -L "$destination" ]]; then
    [[ "$replace" -eq 1 ]] \
        || die "destination already exists; pass --replace to preserve and replace it"
fi

install -d -m 0755 "$bundle_root"
staging="$(mktemp -d "$bundle_root/.ray-99-integration.XXXXXX")"
published=0
backup=""
cleanup() {
    if (
        [[ "$published" -ne 1 && -n "$backup" ]] \
        && [[ -e "$backup" || -L "$backup" ]] \
        && [[ ! -e "$destination" && ! -L "$destination" ]]
    ); then
        mv -- "$backup" "$destination"
    fi
    if [[ "$published" -ne 1 && -n "${staging:-}" && -d "$staging" ]]; then
        rm -rf -- "$staging"
    fi
}
trap cleanup EXIT

python3 - "$api_base_url" "$ca_cert" "$license_public_key" \
    "$license_key_id" "$staging" <<'PY'
import base64
import binascii
import json
import shutil
import stat
import sys
from pathlib import Path
from urllib.parse import urlparse


api_base_url, ca_name, public_key_name, license_key_id, staging_name = sys.argv[1:]
ca_source = Path(ca_name)
public_key_source = Path(public_key_name)
staging = Path(staging_name)


def require_regular_file(path: Path, label: str) -> None:
    try:
        mode = path.lstat().st_mode
    except OSError as exc:
        raise SystemExit(f"{label} must be a readable regular file") from exc
    if not stat.S_ISREG(mode):
        raise SystemExit(f"{label} must be a regular file and not a symlink")


require_regular_file(ca_source, "CA certificate")
require_regular_file(public_key_source, "License public key")

parsed = urlparse(api_base_url)
try:
    port = parsed.port
except ValueError as exc:
    raise SystemExit("API base URL must use HTTPS with explicit port 7443") from exc
if (
    parsed.scheme.lower() != "https"
    or not parsed.hostname
    or port != 7443
    or parsed.username is not None
    or parsed.password is not None
    or parsed.query
    or parsed.fragment
):
    raise SystemExit("API base URL must use HTTPS with explicit port 7443")

if not license_key_id.strip():
    raise SystemExit("License key ID must not be empty")

try:
    public_key_payload = public_key_source.read_bytes().strip()
except OSError as exc:
    raise SystemExit("License public key must be readable") from exc
if len(public_key_payload) != 32:
    try:
        public_key_payload = base64.b64decode(public_key_payload, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise SystemExit("License public key must contain 32 raw or base64 bytes") from exc
if len(public_key_payload) != 32:
    raise SystemExit("License public key must contain 32 raw or base64 bytes")

config = {
    "schema_version": "feetforceplate-client-cloud-default/1",
    "channel": "integration",
    "api_base_url": api_base_url.rstrip("/"),
    "license_key_id": license_key_id.strip(),
    "ca_bundle_resource": "cloud-ca.pem",
    "license_public_key_resource": "license-public.key",
}
(staging / "cloud-default.json").write_text(
    json.dumps(config, ensure_ascii=True, indent=2) + "\n",
    encoding="utf-8",
)
shutil.copyfile(ca_source, staging / "cloud-ca.pem")
shutil.copyfile(public_key_source, staging / "license-public.key")
for name in ("cloud-default.json", "cloud-ca.pem", "license-public.key"):
    (staging / name).chmod(0o644)
staging.chmod(0o755)
PY

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd -P)"
(
    cd "$repository_root"
    PYTHONPATH="$repository_root" python3 - "$staging" "$api_base_url" \
        "$license_key_id" <<'PY'
import sys
from pathlib import Path

from client.cloud.packaged_defaults import load_packaged_cloud_defaults


staging, expected_url, expected_key_id = sys.argv[1:]
defaults = load_packaged_cloud_defaults(Path(staging))
if defaults is None:
    raise SystemExit("staged public bundle was not loadable")
if not defaults.integration_mode:
    raise SystemExit("staged public bundle is not in integration mode")
if defaults.base_url != expected_url.rstrip("/"):
    raise SystemExit("staged public bundle endpoint does not match the request")
if defaults.license_key_id != expected_key_id.strip():
    raise SystemExit("staged public bundle License key ID does not match the request")
PY
)

if [[ -e "$destination" || -L "$destination" ]]; then
    timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
    backup="$bundle_root/ray-99-integration.previous-$timestamp"
    [[ ! -e "$backup" && ! -L "$backup" ]] \
        || die "replacement backup already exists for timestamp $timestamp"
    mv -- "$destination" "$backup"
fi

if ! mv -- "$staging" "$destination"; then
    if [[ -n "$backup" && ! -e "$destination" && ! -L "$destination" ]]; then
        mv -- "$backup" "$destination"
    fi
    die "failed to publish validated bundle"
fi
published=1

echo "bundle=ray-99-integration"
for name in cloud-default.json cloud-ca.pem license-public.key; do
    digest="$(sha256sum "$destination/$name")"
    echo "sha256=${digest%% *} file=$name"
done
