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

    assert "techflex-cloud-foundation==0.2.0" in project["project"]["dependencies"]
    assert "workspace" not in project.get("tool", {}).get("uv", {})
    assert project["tool"]["uv"]["sources"] == {
        "techflex-cloud-foundation": {
            "path": ".foundation-artifacts/techflex_cloud_foundation-0.2.0-py3-none-any.whl"
        }
    }
    assert artifact == {
        "package": "techflex-cloud-foundation",
        "release": "v0.2.0",
        "version": "0.2.0",
        "wheel": "techflex_cloud_foundation-0.2.0-py3-none-any.whl",
        "sha256": "1dd34fb4902fb7359af346e153123e8db12befc6ae8a9de2105e11f80af74303",
    }
