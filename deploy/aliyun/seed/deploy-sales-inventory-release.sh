#!/usr/bin/env bash
set -euo pipefail
umask 077

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
server="${1:-aliyun-agentic}"
release_sha="$(git -C "$repo_root" rev-parse HEAD)"
archive="${TMPDIR:-/private/tmp}/feetforceplate-${release_sha}.tar.gz"
remote_archive="/home/rui/$(basename "$archive")"

git -C "$repo_root" diff --quiet
git -C "$repo_root" diff --cached --quiet
git -C "$repo_root" archive --format=tar.gz --output="$archive" "$release_sha"
archive_sha="$(shasum -a 256 "$archive" | awk '{print $1}')"

scp "$archive" "$server:$remote_archive"

ssh -tt "$server" /bin/bash -s -- "$remote_archive" "$release_sha" "$archive_sha" <<'REMOTE'
set -euo pipefail
archive="$1"
release_sha="$2"
archive_sha="$3"
work_root="/tmp/feetforceplate-release-$release_sha"

sudo -v
sudo -n /bin/bash -s -- "$archive" "$release_sha" "$archive_sha" "$work_root" <<'ROOT'
set -euo pipefail
archive="$1"
release_sha="$2"
archive_sha="$3"
work_root="$4"

actual_sha="$(sha256sum "$archive" | awk '{print $1}')"
if [[ "$actual_sha" != "$archive_sha" ]]; then
    echo "release archive checksum mismatch" >&2
    exit 1
fi
install -d -m 0700 "$work_root"
tar -xzf "$archive" -C "$work_root"
source /etc/feetforceplate/seed.env
bash "$work_root/deploy/aliyun/seed/install-seed-release.sh" \
    "$archive" "$release_sha" "$archive_sha" \
    /etc/feetforceplate/tls/seed.crt \
    /etc/feetforceplate/tls/seed.key \
    "$FEETFORCEPLATE_PUBLIC_BASE_URL" \
    "$FEETFORCEPLATE_BACKUP_AGE_RECIPIENT"
rm -rf -- "$work_root"
ROOT
REMOTE

printf 'release=%s archive_sha256=%s deployment=completed\n' "$release_sha" "$archive_sha"
