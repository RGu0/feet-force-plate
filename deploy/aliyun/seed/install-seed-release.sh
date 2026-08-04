#!/usr/bin/env bash
set -euo pipefail
umask 077

if [[ "${EUID}" -ne 0 ]]; then
    echo "install-seed-release.sh must run as root" >&2
    exit 1
fi
if [[ "$#" -ne 7 ]]; then
    echo "usage: install-seed-release.sh RELEASE_ARCHIVE RELEASE_SHA ARCHIVE_SHA256 TLS_CERT TLS_KEY PUBLIC_BASE_URL AGE_RECIPIENT" >&2
    exit 2
fi

release_archive="$1"
release_sha="$2"
archive_sha256="$3"
tls_certificate="$4"
tls_private_key="$5"
public_base_url="$6"
age_recipient="$7"
service_user="feetforceplate"
service_group="feetforceplate"
database_name="feetforceplate_seed"
secret_file="/etc/feetforceplate/seed.env"

if [[ ! "$release_sha" =~ ^[0-9a-f]{40}$ || ! "$archive_sha256" =~ ^[0-9a-f]{64}$ ]]; then
    echo "release and archive SHA values are invalid" >&2
    exit 2
fi
if [[ ! -f "$release_archive" || ! -f "$tls_certificate" || ! -f "$tls_private_key" ]]; then
    echo "release archive and TLS source files must exist" >&2
    exit 2
fi
if [[ ! "$public_base_url" =~ ^https://[^/]+:7443$ ]]; then
    echo "public base URL must be an HTTPS 7443 origin" >&2
    exit 2
fi
if [[ ! "$age_recipient" =~ ^age1[0-9a-z]+$ ]]; then
    echo "age recipient is invalid" >&2
    exit 2
fi
if [[ "$(sha256sum "$release_archive" | sed 's/ .*//')" != "$archive_sha256" ]]; then
    echo "release archive checksum mismatch" >&2
    exit 1
fi
for command_name in age curl nginx openssl pg_isready psql runuser systemctl tar uv; do
    command -v "$command_name" >/dev/null 2>&1 || {
        echo "required command is missing: $command_name" >&2
        exit 1
    }
done
id "$service_user" >/dev/null 2>&1 || {
    echo "dedicated service identity is missing" >&2
    exit 1
}

install_root="$(mktemp -d /var/lib/feetforceplate/.install-seed.XXXXXX)"
chown root:postgres "$install_root"
chmod 0710 "$install_root"
cleanup() {
    rm -rf -- "$install_root"
}
trap cleanup EXIT
release_source="$install_root/release"
install -d -o "$service_user" -g "$service_group" -m 0700 "$release_source"
tar -xzf "$release_archive" -C "$release_source"
chown -R "$service_user:$service_group" "$release_source"
chmod -R a+rX "$release_source"
chmod 0755 \
    "$release_source/cloud/api/run-seed.sh" \
    "$release_source/scripts/local-env.sh" \
    "$release_source/deploy/aliyun/seed/backup.sh" \
    "$release_source/deploy/aliyun/seed/check-secrets.sh" \
    "$release_source/deploy/aliyun/seed/restore-verify.sh" \
    "$release_source/deploy/aliyun/seed/run-restore-drill.sh" \
    "$release_source/deploy/aliyun/seed/run-live-acceptance.sh" \
    "$release_source/deploy/aliyun/seed/install-layout.sh"

if [[ ! -f "$secret_file" ]]; then
    tenant_password="$(openssl rand -hex 32)"
    activation_password="$(openssl rand -hex 32)"
    platform_password="$(openssl rand -hex 32)"
    backup_password="$(openssl rand -hex 32)"
    install -o "$service_user" -g "$service_group" -m 0600 /dev/null "$secret_file"
    {
        printf 'FEETFORCEPLATE_MIGRATION_DSN=postgresql://migration-disabled@127.0.0.1:5432/%s\n' "$database_name"
        printf 'FEETFORCEPLATE_TENANT_DSN=postgresql://ffp_seed_tenant:%s@127.0.0.1:5432/%s\n' "$tenant_password" "$database_name"
        printf 'FEETFORCEPLATE_ACTIVATION_DSN=postgresql://ffp_seed_activation:%s@127.0.0.1:5432/%s\n' "$activation_password" "$database_name"
        printf 'FEETFORCEPLATE_PLATFORM_DSN=postgresql://ffp_seed_platform:%s@127.0.0.1:5432/%s\n' "$platform_password" "$database_name"
        printf 'FEETFORCEPLATE_BACKUP_DSN=postgresql://ffp_seed_backup:%s@127.0.0.1:5432/%s\n' "$backup_password" "$database_name"
        printf 'FEETFORCEPLATE_TENANT_TOKEN_SECRET=%s\n' "$(openssl rand -hex 32)"
        printf 'FEETFORCEPLATE_PLATFORM_TOKEN_SECRET=%s\n' "$(openssl rand -hex 32)"
        printf 'FEETFORCEPLATE_TENANT_REFRESH_HMAC_KEY=%s\n' "$(openssl rand -hex 32)"
        printf 'FEETFORCEPLATE_PLATFORM_REFRESH_HMAC_KEY=%s\n' "$(openssl rand -hex 32)"
        printf 'FEETFORCEPLATE_TENANT_LOGIN_HMAC_KEY=%s\n' "$(openssl rand -hex 32)"
        printf 'FEETFORCEPLATE_PLATFORM_LOGIN_HMAC_KEY=%s\n' "$(openssl rand -hex 32)"
        printf 'FEETFORCEPLATE_ACTIVATION_HMAC_KEY=%s\n' "$(openssl rand -hex 32)"
        printf 'FEETFORCEPLATE_IDENTITY_LOOKUP_HMAC_KEY=%s\n' "$(openssl rand -hex 32)"
        printf 'FEETFORCEPLATE_IDENTITY_ENCRYPTION_KEY_B64=%s\n' "$(openssl rand -base64 32 | tr -d '\n')"
        printf 'FEETFORCEPLATE_LICENSE_PRIVATE_KEY_B64=%s\n' "$(openssl rand -base64 32 | tr -d '\n')"
        printf 'FEETFORCEPLATE_LICENSE_KEY_ID=license/1\n'
        printf 'FEETFORCEPLATE_TENANT_TOKEN_KEY_ID=tenant/1\n'
        printf 'FEETFORCEPLATE_PLATFORM_TOKEN_KEY_ID=platform/1\n'
        printf 'FEETFORCEPLATE_IDENTITY_KEY_VERSION=identity/1\n'
        printf 'FEETFORCEPLATE_OBJECT_ROOT=/var/lib/feetforceplate/objects\n'
        printf 'FEETFORCEPLATE_BACKUP_ROOT=/var/lib/feetforceplate/backups\n'
        printf 'FEETFORCEPLATE_BACKUP_AGE_RECIPIENT=%s\n' "$age_recipient"
        printf 'FEETFORCEPLATE_BACKUP_RETENTION_DAYS=30\n'
        printf 'FEETFORCEPLATE_PUBLIC_BASE_URL=%s\n' "$public_base_url"
        printf 'FEETFORCEPLATE_TRUSTED_PROXIES=127.0.0.1\n'
        printf 'FEETFORCEPLATE_SEED_ENV_FILE=%s\n' "$secret_file"
    } >"$secret_file"
    chown "$service_user:$service_group" "$secret_file"
    chmod 0600 "$secret_file"
else
    [[ "$(stat -c '%U:%G %a' "$secret_file")" == "$service_user:$service_group 600" ]] || {
        echo "existing seed.env has unsafe ownership or permissions" >&2
        exit 1
    }
    env_value() {
        sed -n "s/^$1=//p" "$secret_file"
    }
    tenant_dsn="$(env_value FEETFORCEPLATE_TENANT_DSN)"
    activation_dsn="$(env_value FEETFORCEPLATE_ACTIVATION_DSN)"
    platform_dsn="$(env_value FEETFORCEPLATE_PLATFORM_DSN)"
    backup_dsn="$(env_value FEETFORCEPLATE_BACKUP_DSN)"
    tenant_password="${tenant_dsn#postgresql://ffp_seed_tenant:}"
    tenant_password="${tenant_password%@127.0.0.1:5432/*}"
    activation_password="${activation_dsn#postgresql://ffp_seed_activation:}"
    activation_password="${activation_password%@127.0.0.1:5432/*}"
    platform_password="${platform_dsn#postgresql://ffp_seed_platform:}"
    platform_password="${platform_password%@127.0.0.1:5432/*}"
    backup_password="${backup_dsn#postgresql://ffp_seed_backup:}"
    backup_password="${backup_password%@127.0.0.1:5432/*}"
fi

if [[ "$(runuser -u postgres -- psql -Atqc "SELECT count(*) FROM pg_database WHERE datname='$database_name'")" == "0" ]]; then
    runuser -u postgres -- createdb "$database_name"
fi
apply_migration() {
    local marker="$1"
    local file="$2"
    if [[ "$(runuser -u postgres -- psql -d "$database_name" -Atqc "SELECT to_regclass('$marker') IS NOT NULL")" != "t" ]]; then
        runuser -u postgres -- psql -v ON_ERROR_STOP=1 -d "$database_name" -f "$file"
    fi
}
apply_migration iam.tenants "$release_source/cloud/migrations/0001_p3_cloud_platform.sql"
apply_migration iam.users "$release_source/cloud/migrations/0002_p5_device_operations.sql"
apply_migration iam.tenant_accounts "$release_source/cloud/migrations/0003_seed_mvp_access_control.sql"
runuser -u postgres -- psql -v ON_ERROR_STOP=1 -d "$database_name" \
    -f "$release_source/cloud/migrations/0004_allow_unsigned_revoked_license.sql"
apply_migration sales.inventory_batches "$release_source/cloud/migrations/0005_sales_inventory_activation.sql"

role_wrapper="$install_root/roles.sql"
{
    printf "\\set database_name '%s'\n" "$database_name"
    printf "\\set tenant_password '%s'\n" "$tenant_password"
    printf "\\set activation_password '%s'\n" "$activation_password"
    printf "\\set platform_password '%s'\n" "$platform_password"
    printf "\\set backup_password '%s'\n" "$backup_password"
    printf "\\ir '%s'\n" "$release_source/deploy/aliyun/seed/postgresql-role-grants.sql"
} >"$role_wrapper"
chown postgres:postgres "$role_wrapper"
chmod 0600 "$role_wrapper"
runuser -u postgres -- psql -v ON_ERROR_STOP=1 -d "$database_name" -f "$role_wrapper"

cp -a /var/lib/pgsql/data/pg_hba.conf "/var/lib/pgsql/data/pg_hba.conf.pre-seed.$(date -u +%Y%m%dT%H%M%SZ)"
install -o postgres -g postgres -m 0600 \
    "$release_source/deploy/aliyun/seed/pg_hba.conf" /var/lib/pgsql/data/pg_hba.conf
runuser -u postgres -- psql -v ON_ERROR_STOP=1 -Atqc "ALTER SYSTEM SET password_encryption = 'scram-sha-256'"
systemctl restart postgresql
pg_isready -h 127.0.0.1 -p 5432 >/dev/null

release_target="/opt/feetforceplate/releases/$release_sha"
if [[ ! -d "$release_target" ]]; then
    bash "$release_source/deploy/aliyun/seed/install-layout.sh" "$release_source" "$release_sha"
elif [[ ! -f "$release_target/.release-sha" || "$(cat "$release_target/.release-sha")" != "$release_sha" ]]; then
    echo "existing release target does not match the requested SHA" >&2
    exit 1
else
    ln -sfn "$release_target" /opt/feetforceplate/app.next
    mv -Tf /opt/feetforceplate/app.next /opt/feetforceplate/app
fi

install -o root -g root -m 0600 "$tls_private_key" /etc/feetforceplate/tls/seed.key
install -o root -g root -m 0644 "$tls_certificate" /etc/feetforceplate/tls/seed.crt
if [[ ! -f /etc/nginx/nginx.conf.pre-seed ]]; then
    cp -a /etc/nginx/nginx.conf /etc/nginx/nginx.conf.pre-seed
fi
install -o root -g root -m 0644 "$release_target/deploy/aliyun/seed/nginx.conf" /etc/nginx/nginx.conf
install -o root -g root -m 0644 "$release_target/deploy/aliyun/seed/feetforceplate-seed.service" \
    /etc/systemd/system/feetforceplate-seed.service
install -o root -g root -m 0644 "$release_target/deploy/aliyun/seed/feetforceplate-backup.service" \
    /etc/systemd/system/feetforceplate-backup.service
install -o root -g root -m 0644 "$release_target/deploy/aliyun/seed/feetforceplate-backup.timer" \
    /etc/systemd/system/feetforceplate-backup.timer
systemctl daemon-reload
systemctl enable feetforceplate-seed.service feetforceplate-backup.timer nginx
systemctl restart feetforceplate-seed.service

backend_ready=false
for _ in $(seq 1 90); do
    if curl -fsS http://127.0.0.1:8743/health/ready >/dev/null; then
        backend_ready=true
        break
    fi
    sleep 2
done
if [[ "$backend_ready" != "true" ]]; then
    journalctl -u feetforceplate-seed.service -n 80 --no-pager >&2
    echo "seed backend did not become ready; existing 7443 service was not changed" >&2
    exit 1
fi

preflight_conf="$install_root/nginx-preflight.conf"
sed -e 's/listen 7443 ssl;/listen 17443 ssl;/' \
    -e 's/listen \[::\]:7443 ssl;/listen [::]:17443 ssl;/' \
    "$release_target/deploy/aliyun/seed/nginx-feetforceplate-seed.conf" >"$preflight_conf"
install -o root -g root -m 0644 "$preflight_conf" /etc/nginx/conf.d/feetforceplate-seed.conf
nginx -t
systemctl restart nginx
curl -kfsS https://127.0.0.1:17443/health/ready >/dev/null
systemctl stop nginx
install -o root -g root -m 0644 \
    "$release_target/deploy/aliyun/seed/nginx-feetforceplate-seed.conf" \
    /etc/nginx/conf.d/feetforceplate-seed.conf
nginx -t

old_pid="$(ss -ltnp '( sport = :7443 )' | sed -n 's/.*pid=\([0-9][0-9]*\).*/\1/p' | head -1)"
if [[ -n "$old_pid" ]]; then
    old_command="$(tr '\0' ' ' <"/proc/$old_pid/cmdline")"
    if [[ "$old_command" != *"uvicorn cloud.api.integration:app_from_environment"* ]]; then
        echo "7443 is owned by an unexpected process; refusing cutover" >&2
        exit 1
    fi
    kill -TERM "$old_pid"
    for _ in $(seq 1 30); do
        kill -0 "$old_pid" >/dev/null 2>&1 || break
        sleep 1
    done
    if kill -0 "$old_pid" >/dev/null 2>&1; then
        echo "legacy 7443 process did not stop cleanly" >&2
        exit 1
    fi
fi

systemctl start nginx
curl -kfsS https://127.0.0.1:7443/health/ready >/dev/null
systemctl start feetforceplate-backup.service
systemctl start feetforceplate-backup.timer

printf 'seed_release=%s backend=ready ingress=7443 backup=verified-once secrets=not-printed\n' "$release_sha"
