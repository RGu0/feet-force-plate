from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from verify_foundation_release_lock import locked_foundation_release  # noqa: E402


def test_committed_foundation_release_matches_public_lock() -> None:
    url, digest = locked_foundation_release(ROOT / "pyproject.toml", ROOT / "uv.lock")
    assert url.startswith("https://github.com/RGu0/techflex-cloud-foundation/releases/download/")
    assert len(digest) == 64


def test_public_release_url_must_match_lock(tmp_path: Path) -> None:
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    lock = (ROOT / "uv.lock").read_text(encoding="utf-8")
    project_path = tmp_path / "pyproject.toml"
    lock_path = tmp_path / "uv.lock"
    project_path.write_text(project.replace("releases/download/v0.9.4", "releases/download/v0.9.5"), encoding="utf-8")
    lock_path.write_text(lock, encoding="utf-8")
    with pytest.raises(RuntimeError, match="release URL differs"):
        locked_foundation_release(project_path, lock_path)


def test_missing_locked_wheel_hash_is_rejected(tmp_path: Path) -> None:
    project_path = ROOT / "pyproject.toml"
    lock = (ROOT / "uv.lock").read_text(encoding="utf-8")
    lock_path = tmp_path / "uv.lock"
    lock_path.write_text(lock.replace(
        "sha256:86352bc722134ed45a5ff1b37c6201b6525a2f8de771bd86009cfc338bcfe79d",
        "sha256:missing",
    ), encoding="utf-8")
    with pytest.raises(RuntimeError, match="SHA-256 is absent"):
        locked_foundation_release(project_path, lock_path)
