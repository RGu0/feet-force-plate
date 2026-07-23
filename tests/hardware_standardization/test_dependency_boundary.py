from __future__ import annotations

import ast
from pathlib import Path


PACKAGE = Path("client/hardware_standardization")
FORBIDDEN_PREFIXES = (
    "client.app",
    "client.local_analysis",
    "client.reporting",
    "client.spool",
    "cloud",
    "serial",
    "httpx",
)


def test_generic_physical_array_modules_do_not_depend_on_ui_cloud_analysis_or_serial() -> None:
    for path in PACKAGE.glob("*.py"):
        if path.name == "do_p4864.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = [
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        ] + [
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        ]
        assert not any(
            imported == prefix or imported.startswith(f"{prefix}.")
            for imported in imports
            for prefix in FORBIDDEN_PREFIXES
        ), path
