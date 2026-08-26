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

    assert "techflex-cloud-foundation==0.1.1" in project["project"]["dependencies"]
    assert "workspace" not in project.get("tool", {}).get("uv", {})
    assert project["tool"]["uv"]["sources"] == {
        "techflex-cloud-foundation": {
            "path": ".foundation-artifacts/techflex_cloud_foundation-0.1.1-py3-none-any.whl"
        }
    }
    assert artifact == {
        "package": "techflex-cloud-foundation",
        "release": "v0.1.1",
        "version": "0.1.1",
        "wheel": "techflex_cloud_foundation-0.1.1-py3-none-any.whl",
        "sha256": "26a8647541398ab95c8d039c86e8b440815318960686ba94174c6043bb469107",
    }
