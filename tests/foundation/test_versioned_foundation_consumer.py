from __future__ import annotations

from pathlib import Path
import tomllib


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_feetforceplate_uses_the_locked_github_release_wheel() -> None:
    project = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    lock_text = (PROJECT_ROOT / "uv.lock").read_text(encoding="utf-8")
    lock = tomllib.loads(lock_text)
    release_url = (
        "https://github.com/RGu0/techflex-cloud-foundation/releases/download/"
        "v0.9.2/techflex_cloud_foundation-0.9.2-py3-none-any.whl"
    )
    foundation = next(
        package for package in lock["package"]
        if package["name"] == "techflex-cloud-foundation"
    )

    assert "techflex-cloud-foundation==0.9.2" in project["project"]["dependencies"]
    assert "workspace" not in project.get("tool", {}).get("uv", {})
    assert project["tool"]["uv"]["sources"] == {
        "techflex-cloud-foundation": {"url": release_url}
    }
    assert foundation["version"] == "0.9.2"
    assert foundation["source"] == {"url": release_url}
    assert foundation["wheels"][0]["url"] == release_url
    assert foundation["wheels"][0]["hash"] == (
        "sha256:61608c0d7974db31b8a4920626e97c8eb2e64639e9ce687b525d09a1f256878a"
    )
    assert ".foundation-artifacts" not in lock_text
