from __future__ import annotations

import json
from pathlib import Path
import tomllib


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_feetforceplate_uses_a_locked_private_foundation_artifact() -> None:
    project = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    artifact = json.loads(
        (PROJECT_ROOT / "foundation-artifact.lock.json").read_text(encoding="utf-8")
    )

    assert "techflex-cloud-foundation==0.3.0" in project["project"]["dependencies"]
    assert "workspace" not in project.get("tool", {}).get("uv", {})
    assert project["tool"]["uv"]["sources"] == {
        "techflex-cloud-foundation": {
            "path": ".foundation-artifacts/techflex_cloud_foundation-0.3.0-py3-none-any.whl"
        }
    }
    assert artifact == {
        "package": "techflex-cloud-foundation",
        "release": "v0.3.0",
        "version": "0.3.0",
        "wheel": "techflex_cloud_foundation-0.3.0-py3-none-any.whl",
        "sha256": "6790d4f770a0ad0756885f6b58555d4da8c7ef3aad3274b6df8f583b6e63e089",
    }
