from __future__ import annotations

import os
from pathlib import Path
import stat


ROOT = Path(__file__).resolve().parents[2] / "deploy/aliyun/seed"


def test_integration_public_bundle_helper_is_root_gated_and_secret_free() -> None:
    path = ROOT / "build-integration-public-bundle.sh"
    text = path.read_text(encoding="utf-8")
    assert path.stat().st_mode & stat.S_IXUSR
    assert "must run as root" in text
    assert "seed.env" not in text
    assert "systemctl" not in text
    assert "os.O_NOFOLLOW" in text
    assert "os.fstat" in text
    assert "copyfile(" not in text
    assert "copyfileobj(" not in text
    assert "--help|-h" not in text
    assert ".ray-99-integration.lock" in text
    assert "mv -T" in text


def test_runtime_declares_native_oss_and_rotating_ecs_role_dependencies() -> None:
    repository = ROOT.parents[2]
    project = (repository / "pyproject.toml").read_text()
    lock = (repository / "uv.lock").read_text()
    for package in ("alibabacloud-oss-v2", "alibabacloud-credentials"):
        assert package in project
        assert package in lock


def test_systemd_service_is_unprivileged_hardened_and_loopback_only() -> None:
    text = (ROOT / "feetforceplate-seed.service").read_text()
    for token in (
        "User=feetforceplate", "Group=feetforceplate", "NoNewPrivileges=true",
        "PrivateTmp=true", "ProtectSystem=strict", "ProtectHome=true",
        "ReadWritePaths=/var/lib/feetforceplate/objects",
        "ReadWritePaths=/var/lib/feetforceplate/validation-telemetry",
        "ReadWritePaths=/var/lib/feetforceplate/runtime",
        "FEETFORCEPLATE_VENV=/var/lib/feetforceplate/runtime/venv",
        "XDG_CACHE_HOME=/var/lib/feetforceplate/runtime/cache",
        "EnvironmentFile=/etc/feetforceplate/seed.env", "Restart=on-failure",
        "FEETFORCEPLATE_BIND_HOST=127.0.0.1", "FEETFORCEPLATE_BIND_PORT=8743",
    ):
        assert token in text
    assert "User=root" not in text


def test_nginx_7443_ingress_has_tls_limits_rates_and_no_private_static_mapping() -> None:
    text = (ROOT / "nginx-feetforceplate-seed.conf").read_text()
    for token in (
        "listen 7443 ssl", "ssl_protocols TLSv1.2 TLSv1.3",
        "client_max_body_size", "client_header_timeout", "client_body_timeout",
        "proxy_connect_timeout", "proxy_read_timeout", "limit_req_zone",
        "limit_req zone=seed_general", "limit_req zone=seed_auth",
        "X-Request-ID", "proxy_pass http://127.0.0.1:8743", "limit_req_status 429",
    ):
        assert token in text
    assert "Authorization" not in text.split("log_format", 1)[1].split(";", 1)[0]
    assert "/var/lib/feetforceplate/objects" not in text
    assert "/var/lib/feetforceplate/backups" not in text
    assert "alias " not in text and "root " not in text


def test_postgres_roles_are_non_privileged_and_network_is_loopback_only() -> None:
    text = (ROOT / "postgresql-role-grants.sql").read_text()
    for role in ("ffp_seed_tenant", "ffp_seed_activation", "ffp_seed_platform"):
        assert role in text
    assert text.count("NOSUPERUSER") >= 3
    assert text.count("NOBYPASSRLS") >= 3
    assert "listen_addresses = '127.0.0.1,::1'" in text
    assert "0.0.0.0" not in text
    assert text.count("NOBYPASSRLS") >= 3
    assert "ffp_seed_backup" in text and "BYPASSRLS" in text
    assert "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA sales TO ffp_seed_backup;" in text
    assert "SET password_encryption = 'scram-sha-256'" in text


def test_managed_nginx_and_postgres_configs_expose_only_seed_loopback_boundaries() -> None:
    nginx = (ROOT / "nginx.conf").read_text()
    pg_hba = (ROOT / "pg_hba.conf").read_text()
    assert "include /etc/nginx/conf.d/*.conf" in nginx
    assert "listen" not in nginx
    assert "127.0.0.1/32" in pg_hba and "::1/128" in pg_hba
    assert "trust" not in pg_hba
    assert "0.0.0.0" not in pg_hba
    for role in (
        "ffp_seed_tenant", "ffp_seed_activation", "ffp_seed_platform", "ffp_seed_backup",
    ):
        assert role in pg_hba


def test_layout_and_secret_checker_enforce_ownership_without_printing_values() -> None:
    layout = (ROOT / "install-layout.sh").read_text()
    checker = (ROOT / "check-secrets.sh").read_text()
    for path in (
        "/opt/feetforceplate/releases", "/opt/feetforceplate/app",
        "/etc/feetforceplate/seed.env", "/var/lib/feetforceplate/objects",
        "/var/lib/feetforceplate/backups",
        "/var/lib/feetforceplate/validation-telemetry",
        "/var/lib/feetforceplate/runtime",
    ):
        assert path in layout
    assert "-user root" in layout
    assert "must not be root-owned" in layout
    assert "0600" in layout and "0700" in layout
    assert "stat" in checker and "printf" in checker
    assert "source " not in checker and "cat " not in checker
    assert "cut " not in checker and "awk " not in checker


def test_host_prerequisites_are_idempotent_and_do_not_cut_over_7443() -> None:
    text = (ROOT / "host-prerequisites.sh").read_text()
    for token in (
        "dnf install -y nginx postgresql-server postgresql-contrib",
        "/var/lib/pgsql/data/PG_VERSION",
        "postgresql-setup --initdb",
        "systemctl enable --now postgresql",
        "useradd --system --no-create-home",
        "/var/lib/feetforceplate/runtime",
        "/usr/local/bin/age-keygen",
    ):
        assert token in text
    assert "systemctl stop" not in text
    assert "pkill" not in text
    assert "kill " not in text
    assert "nginx-feetforceplate-seed.conf" not in text


def test_release_installer_preflights_before_exact_legacy_cutover() -> None:
    path = ROOT / "install-seed-release.sh"
    text = path.read_text()
    for token in (
        "sha256sum", "scram-sha-256", "17443", "/health/ready",
        "uvicorn cloud.api.integration:app_from_environment", "kill -TERM \"$old_pid\"",
        "systemctl start feetforceplate-backup.service", "secrets=not-printed",
    ):
        assert token in text
    assert text.index("https://127.0.0.1:17443/health/ready") < text.index("kill -TERM")
    assert text.index("http://127.0.0.1:8743/health/ready") < text.index("kill -TERM")
    assert text.index("kill -TERM") < text.index("systemctl start nginx", text.index("kill -TERM"))
    if os.name != "nt":
        assert path.stat().st_mode & stat.S_IXUSR
    assert "0004_allow_unsigned_revoked_license.sql" in text
    assert "0005_sales_inventory_activation.sql" in text
    assert "0006_inventory_activation_pairing.sql" in text
    assert "apply_migration_if_column_missing sales inventory_batches activation_binding_mode" in text
    assert "install_tls_file" in text
    assert "readlink -f" in text
    assert '"$release_source/deploy/aliyun/seed/run-restore-drill.sh"' in text
    assert '"$release_source/deploy/aliyun/seed/configure-oss.sh"' in text


def test_oss_configuration_uses_ecs_role_without_long_lived_access_keys() -> None:
    path = ROOT / "configure-oss.sh"
    text = path.read_text()
    for token in (
        "FEETFORCEPLATE_OBJECT_BACKEND=aliyun-oss",
        "FEETFORCEPLATE_OSS_REGION",
        "FEETFORCEPLATE_OSS_BUCKET",
        "FEETFORCEPLATE_OSS_ENDPOINT",
        "FEETFORCEPLATE_OSS_SERVER_SIDE_ENCRYPTION",
        "FEETFORCEPLATE_OSS_ECS_RAM_ROLE",
        "FEETFORCEPLATE_VALIDATION_TELEMETRY_ROOT",
        "oss_configuration=updated",
        "values=not-printed",
    ):
        assert token in text
    assert "ACCESS_KEY" not in text
    assert "source " not in text
    if os.name != "nt":
        assert path.stat().st_mode & stat.S_IXUSR


def test_backup_metadata_includes_sales_inventory_schema_version() -> None:
    text = (ROOT / "backup.sh").read_text()
    assert "0005_sales_inventory_activation" in text
    assert "0006_inventory_activation_pairing" in text


def test_sales_inventory_server_bootstrap_reads_release_manifest() -> None:
    text = (ROOT / "feetforceplate-sales-inventory-server.sh").read_text()
    assert 'release_manifest="/home/rui/feetforceplate-sales-inventory-release.env"' in text
    assert 'source "$release_manifest"' in text
    assert 'release_sha="${RELEASE_SHA:?missing RELEASE_SHA}"' in text
    assert 'archive_sha="${ARCHIVE_SHA256:?missing ARCHIVE_SHA256}"' in text
    assert 'archive="${ARCHIVE_PATH:?missing ARCHIVE_PATH}"' in text


def test_systemd_entry_scripts_are_executable() -> None:
    for relative in (
        "cloud/api/run-seed.sh",
        "scripts/local-env.sh",
        "deploy/aliyun/seed/backup.sh",
        "deploy/aliyun/seed/check-secrets.sh",
        "deploy/aliyun/seed/restore-verify.sh",
        "deploy/aliyun/seed/run-restore-drill.sh",
        "deploy/aliyun/seed/run-live-acceptance.sh",
        "deploy/aliyun/seed/configure-oss.sh",
        "deploy/aliyun/seed/resume-seed-cutover.sh",
    ):
        path = ROOT.parents[2] / relative
        if os.name != "nt":
            assert path.stat().st_mode & stat.S_IXUSR


def test_resume_cutover_requires_persistent_readiness_before_stopping_legacy() -> None:
    text = (ROOT / "resume-seed-cutover.sh").read_text()
    assert text.index("http://127.0.0.1:8743/health/ready") < text.index("kill -TERM")
    assert text.index("https://127.0.0.1:17443/health/ready") < text.index("kill -TERM")
    assert "uvicorn cloud.api.integration:app_from_environment" in text
    assert "\"postgres\":\"ready\"" in text
    assert "\"object_store\":\"ready\"" in text
    assert "systemctl start feetforceplate-backup.service" in text


def test_live_acceptance_uses_the_service_owned_uv_runtime() -> None:
    text = (ROOT / "run-live-acceptance.sh").read_text()
    assert text.count("FEETFORCEPLATE_VENV=/var/lib/feetforceplate/runtime/venv") >= 3
    assert text.count("XDG_CACHE_HOME=/var/lib/feetforceplate/runtime/cache") >= 3
    assert "PYTEST_DISABLE_PLUGIN_AUTOLOAD=1" in text
    assert "scripts/verify_aliyun_oss_live.py" in text
    assert "aliyun-oss-summary.json" in text
