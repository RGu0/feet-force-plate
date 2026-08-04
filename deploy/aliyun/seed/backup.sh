#!/usr/bin/env bash
set -euo pipefail
umask 077

: "${FEETFORCEPLATE_BACKUP_DSN:?backup DSN is required}"
: "${FEETFORCEPLATE_OBJECT_ROOT:?object root is required}"
: "${FEETFORCEPLATE_BACKUP_ROOT:?backup root is required}"
: "${FEETFORCEPLATE_BACKUP_AGE_RECIPIENT:?age public recipient is required}"

RETENTION_DAYS="${FEETFORCEPLATE_BACKUP_RETENTION_DAYS:-30}"
if [[ ! "$RETENTION_DAYS" =~ ^[0-9]+$ ]] || (( RETENTION_DAYS < 1 )); then
    echo "backup retention must be a positive day count" >&2
    exit 2
fi
if [[ ! -d "$FEETFORCEPLATE_OBJECT_ROOT" || ! -d "$FEETFORCEPLATE_BACKUP_ROOT" ]]; then
    echo "object and backup roots must already exist" >&2
    exit 2
fi

implementation_sha="$(cat /opt/feetforceplate/app/.release-sha)"
if [[ ! "$implementation_sha" =~ ^[0-9a-f]{40}$ ]]; then
    echo "installed release SHA is invalid" >&2
    exit 2
fi
backup_id="$(date -u +%Y%m%dT%H%M%SZ)-${implementation_sha:0:12}"
stage="$FEETFORCEPLATE_BACKUP_ROOT/.staging-$backup_id"
bundle_stage="$FEETFORCEPLATE_BACKUP_ROOT/.staging-$backup_id.age"
bundle_final="$FEETFORCEPLATE_BACKUP_ROOT/$backup_id.tar.age"
mkdir -m 0700 "$stage"
cleanup() {
    rm -rf -- "$stage"
    rm -f -- "$bundle_stage"
    rm -f -- "$bundle_final.sha256.tmp"
}
trap cleanup EXIT

pg_dump --format=custom --no-owner --no-privileges \
    --file="$stage/database.dump" "$FEETFORCEPLATE_BACKUP_DSN"

(
    cd "$FEETFORCEPLATE_OBJECT_ROOT"
    find . -type f ! -path './.staging/*' -print0 \
        | sort -z \
        | xargs -0 -r sha256sum
) >"$stage/object-manifest.sha256"
tar -C "$FEETFORCEPLATE_OBJECT_ROOT" --exclude='./.staging' -cf "$stage/objects.tar" .

schema_versions="0001_p3_cloud_platform,0002_p5_device_operations,0003_seed_mvp_access_control,0004_allow_unsigned_revoked_license,0005_sales_inventory_activation"
printf '{"backup_id":"%s","implementation_sha":"%s","schema_versions":"%s","created_at":"%s"}\n' \
    "$backup_id" "$implementation_sha" "$schema_versions" "$(date -u +%FT%TZ)" \
    >"$stage/metadata.json"

tar -C "$stage" -cf - database.dump objects.tar object-manifest.sha256 metadata.json \
    | age --recipient "$FEETFORCEPLATE_BACKUP_AGE_RECIPIENT" --output "$bundle_stage"
sync -f "$bundle_stage"
mv "$bundle_stage" "$bundle_final"
sha256sum "$bundle_final" >"$bundle_final.sha256.tmp"
sync -f "$bundle_final.sha256.tmp"
mv "$bundle_final.sha256.tmp" "$bundle_final.sha256"
sync -f "$FEETFORCEPLATE_BACKUP_ROOT"
trap - EXIT
rm -rf -- "$stage"

mapfile -t verified_bundles < <(
    find "$FEETFORCEPLATE_BACKUP_ROOT" -maxdepth 1 -type f -name '*.tar.age' -print | sort
)
newest_bundle="${verified_bundles[-1]:-}"
cutoff_epoch="$(date -u -d "$RETENTION_DAYS days ago" +%s)"
for candidate in "${verified_bundles[@]}"; do
    [[ "$candidate" == "$newest_bundle" ]] && continue
    [[ -f "$candidate.sha256" ]] || continue
    candidate_epoch="$(stat -c '%Y' "$candidate")"
    if (( candidate_epoch < cutoff_epoch )); then
        rm -f -- "$candidate" "$candidate.sha256"
    fi
done

printf 'backup_id=%s bundle_sha256=%s\n' \
    "$backup_id" "$(sha256sum "$bundle_final" | sed 's/ .*//')"
