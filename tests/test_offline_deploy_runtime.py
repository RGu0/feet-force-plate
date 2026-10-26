from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zipfile

import pytest

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


def test_offline_check_runs_outside_the_root_executed_tree() -> None:
    # The check runs as feetforceplate, which is not in install_root's group
    # (postgres). Root later executes files from install_root/release, so the
    # service user must not reach it: the check runs on a separate copy.
    installer = _text("install-seed-release.sh")
    assert 'chmod 0710 "$install_root"' in installer
    assert re.search(r'chmod 0711 "\$offline_check_root"', installer)
    check = installer.index("UV_OFFLINE=1")
    assert installer.index('cp -a "$release_source" "$offline_check_root/release"') < check
    assert '"$offline_check_root/release/dev" setup' in installer
    assert '"$release_source/dev"' not in installer
    assert 'rm -rf -- "$install_root" "$offline_check_root"' in installer


def test_operator_script_uploads_checked_wheel() -> None:
    deploy = _text("deploy-sales-inventory-release.sh")
    assert "verify_foundation_release_lock.py" in deploy
    assert "foundation release wheel digest mismatch" in deploy
    assert '"$remote_foundation_wheel"' in deploy


def test_services_resolve_dependencies_offline() -> None:
    for unit in ("feetforceplate-seed.service", "feetforceplate-backup.service"):
        assert "Environment=UV_OFFLINE=1" in _text(unit)


def test_installer_seeds_uv_cache_from_uploaded_wheel_before_offline_check() -> None:
    installer = _text("install-seed-release.sh")
    warm = installer.index("warm_foundation_wheel_cache.py")
    assert installer.index('"$foundation_wheel" "$offline_check_root') < warm
    assert warm < installer.index("UV_OFFLINE=1")
    assert '"$foundation_url" "$foundation_sha256"' in installer
    assert "nothing was changed" in installer[warm:installer.index("UV_OFFLINE=1")]


def _wheel(directory: Path, version: str) -> Path:
    name = "ffp_warmup_probe"
    path = directory / f"{name}-{version}-py3-none-any.whl"
    dist_info = f"{name}-{version}.dist-info"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(f"{name}/__init__.py", "")
        archive.writestr(
            f"{dist_info}/METADATA",
            f"Metadata-Version: 2.1\nName: ffp-warmup-probe\nVersion: {version}\n",
        )
        archive.writestr(
            f"{dist_info}/WHEEL",
            "Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        )
        archive.writestr(f"{dist_info}/RECORD", "")
    return path


def _warm(wheel: Path, url: str, digest: str, cache: Path) -> int:
    env = {**os.environ, "UV_CACHE_DIR": str(cache)}
    return subprocess.run(
        [sys.executable, str(SEED / "warm_foundation_wheel_cache.py"), str(wheel), url, digest,
         shutil.which("uv") or "uv"],
        env=env, capture_output=True, check=False, timeout=120,
    ).returncode


def _offline_install(url: str, cache: Path, target: Path) -> int:
    env = {**os.environ, "UV_CACHE_DIR": str(cache), "UV_OFFLINE": "1"}
    return subprocess.run(
        ["uv", "pip", "install", "--no-deps", "--target", str(target), url],
        env=env, capture_output=True, check=False, timeout=120,
    ).returncode


needs_tools = pytest.mark.skipif(
    shutil.which("uv") is None or shutil.which("openssl") is None,
    reason="uv and openssl are required for the cache warm-up rehearsal",
)


@needs_tools
@pytest.mark.parametrize("version", ["0.2.0", "0.3.0"])
def test_uploaded_wheel_satisfies_offline_resolution_on_an_empty_cache(tmp_path: Path, version: str) -> None:
    wheel = _wheel(tmp_path, version)
    url = f"https://github.com/example/probe/releases/download/v{version}/{wheel.name}"
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    cache = tmp_path / "empty-cache"

    assert _offline_install(url, cache, tmp_path / "before") != 0
    assert _warm(wheel, url, digest, cache) == 0
    assert _offline_install(url, cache, tmp_path / "after") == 0


@needs_tools
def test_wrong_or_missing_wheel_leaves_the_cache_untouched(tmp_path: Path) -> None:
    wheel = _wheel(tmp_path, "0.2.0")
    url = f"https://github.com/example/probe/releases/download/v0.2.0/{wheel.name}"
    cache = tmp_path / "cache"

    assert _warm(wheel, url, "0" * 64, cache) != 0
    assert _warm(tmp_path / "missing.whl", url, "0" * 64, cache) != 0
    assert not cache.exists()
