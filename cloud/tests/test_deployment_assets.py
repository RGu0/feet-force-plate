from __future__ import annotations

from pathlib import Path
import stat


ROOT = Path(__file__).resolve().parents[2] / "deploy/aliyun/seed"


def test_systemd_service_is_unprivileged_hardened_and_loopback_only() -> None:
    text = (ROOT / "feetforceplate-seed.service").read_text()
    for token in (
        "User=feetforceplate", "Group=feetforceplate", "NoNewPrivileges=true",
        "PrivateTmp=true", "ProtectSystem=strict", "ProtectHome=true",
        "ReadWritePaths=/var/lib/feetforceplate/objects",
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
    assert path.stat().st_mode & stat.S_IXUSR


def test_systemd_entry_scripts_are_executable() -> None:
    for relative in (
        "cloud/api/run-seed.sh",
        "scripts/local-env.sh",
        "deploy/aliyun/seed/backup.sh",
        "deploy/aliyun/seed/check-secrets.sh",
        "deploy/aliyun/seed/restore-verify.sh",
        "deploy/aliyun/seed/run-live-acceptance.sh",
        "deploy/aliyun/seed/resume-seed-cutover.sh",
    ):
        path = ROOT.parents[2] / relative
        assert path.stat().st_mode & stat.S_IXUSR


def test_resume_cutover_requires_persistent_readiness_before_stopping_legacy() -> None:
    text = (ROOT / "resume-seed-cutover.sh").read_text()
    assert text.index("http://127.0.0.1:8743/health/ready") < text.index("kill -TERM")
    assert text.index("https://127.0.0.1:17443/health/ready") < text.index("kill -TERM")
    assert "uvicorn cloud.api.integration:app_from_environment" in text
    assert "\"postgres\":\"ready\"" in text
    assert "\"object_store\":\"ready\"" in text
    assert "systemctl start feetforceplate-backup.service" in text
