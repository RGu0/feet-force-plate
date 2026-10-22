from __future__ import annotations

from pathlib import Path
import re

SEED = Path(__file__).resolve().parents[1] / "deploy" / "aliyun" / "seed"


def _text(name: str) -> str:
    return (SEED / name).read_text(encoding="utf-8")


def test_installer_does_not_fetch_foundation_wheel_from_host() -> None:
    installer = _text("install-seed-release.sh")
    assert "--output \"$foundation_wheel\" \"$foundation_url\"" not in installer
    assert "foundation_wheel_source" in installer
    assert "foundation release wheel digest mismatch" in installer


def test_installer_proves_offline_resolution_before_migrations() -> None:
    installer = _text("install-seed-release.sh")
    preflight = installer.index("UV_OFFLINE=1")
    assert preflight < installer.index("apply_migration iam.tenants")
    assert preflight < installer.index("createdb")


def test_service_user_can_reach_the_offline_check() -> None:
    # The check runs as feetforceplate, which is not in the install root's
    # group (postgres); the root must stay traversable by others.
    installer = _text("install-seed-release.sh")
    mode = re.search(r'chmod (0[0-7]{3}) "\$install_root"', installer)
    assert mode is not None
    assert int(mode.group(1), 8) & 0o001
    assert installer.index(mode.group(0)) < installer.index("UV_OFFLINE=1")


def test_operator_script_uploads_checked_wheel() -> None:
    deploy = _text("deploy-sales-inventory-release.sh")
    assert "verify_foundation_release_lock.py" in deploy
    assert "foundation release wheel digest mismatch" in deploy
    assert '"$remote_foundation_wheel"' in deploy


def test_services_resolve_dependencies_offline() -> None:
    for unit in ("feetforceplate-seed.service", "feetforceplate-backup.service"):
        assert "Environment=UV_OFFLINE=1" in _text(unit)
