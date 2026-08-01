"""Architectural guard: upper layers consume hardware contracts, not drivers."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).parents[2]
UPPER_LAYER_DIRECTORIES = (ROOT / "client/app", ROOT / "client/local_analysis")
FORBIDDEN_MODULE_PREFIXES = (
    "client.device",
    "client.hardware_standardization.do_p4864",
    "client.hardware_standardization.device_specification",
)


def _imports(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.append(node.module)
    return tuple(found)


def test_application_and_analysis_layers_do_not_select_device_drivers_or_raw_frames() -> None:
    violations: list[str] = []
    for directory in UPPER_LAYER_DIRECTORIES:
        for path in directory.rglob("*.py"):
            for imported in _imports(path):
                if imported.startswith(FORBIDDEN_MODULE_PREFIXES):
                    violations.append(f"{path.relative_to(ROOT)} -> {imported}")
    assert violations == [], "\n".join(violations)
