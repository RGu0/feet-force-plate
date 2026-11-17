"""Export public mobile artifacts from the installed, locked foundation wheel."""
from __future__ import annotations

import json
from pathlib import Path

from techflex_cloud_foundation.server.contract_export import build_openapi, build_vectors


def export(output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    for name, document in (("openapi.json", build_openapi()), ("vectors.json", build_vectors())):
        (output / name).write_text(
            json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    export(Path(__file__).resolve().parents[1] / "cloud/contracts/mobile")
