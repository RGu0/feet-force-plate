#!/usr/bin/env bash
set -euo pipefail
umask 077

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
server="${1:-aliyun-agentic}"
release_sha="$(git -C "$repo_root" rev-parse HEAD)"
archive="${TMPDIR:-/private/tmp}/feetforceplate-${release_sha}.tar.gz"
remote_archive="/home/rui/$(basename "$archive")"
remote_wrapper_source="$repo_root/deploy/aliyun/seed/feetforceplate-seed-release-server.sh"
remote_wrapper="/home/rui/$(basename "$remote_wrapper_source")"

git -C "$repo_root" diff --quiet
git -C "$repo_root" diff --cached --quiet
git -C "$repo_root" archive --format=tar.gz --output="$archive" "$release_sha"
archive_sha="$(shasum -a 256 "$archive" | awk '{print $1}')"

scp "$archive" "$remote_wrapper_source" "$server:/home/rui/"

ssh -tt "$server" sudo /bin/bash "$remote_wrapper" \
    "$remote_archive" "$release_sha" "$archive_sha"

printf 'release=%s archive_sha256=%s deployment=completed\n' "$release_sha" "$archive_sha"
