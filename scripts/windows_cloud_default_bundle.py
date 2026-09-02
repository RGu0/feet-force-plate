#!/usr/bin/env python3
"""Prepare or validate a public-only Windows cloud-default delivery."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from client.cloud.windows_bundle import (  # noqa: E402
    materialize_validated_windows_cloud_runtime,
    prepare_windows_cloud_default_bundle,
    validate_windows_cloud_default_bundle,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--source", type=Path, required=True)
    prepare.add_argument("--approval", type=Path, required=True)
    prepare.add_argument("--approval-signature", type=Path, required=True)
    prepare.add_argument("--delivery", type=Path, required=True)
    prepare.add_argument("--project-root", type=Path, required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("--delivery", type=Path, required=True)
    validate.add_argument("--project-root", type=Path, required=True)
    validate.add_argument("--settings-output", type=Path)
    return parser


def _settings_payload(
    settings: object, *, runtime_directory: Path | None = None
) -> dict[str, object]:
    payload = {
        "api_base_url": settings.base_url,
        "ca_bundle": str(settings.ca_bundle),
        "integration_mode": settings.integration_mode,
        "license_key_id": settings.license_key_id,
        "license_public_key_file": str(settings.license_public_key),
    }
    if runtime_directory is not None:
        payload["runtime_directory"] = str(runtime_directory)
    return payload


def _require_controlled_project_root(project_root: Path) -> Path:
    candidate = Path(project_root).expanduser().resolve()
    if candidate != PROJECT_ROOT.resolve():
        raise ValueError("ProjectRoot must be the controlled source root")
    return candidate


def _write_settings_output(path: Path, payload: dict[str, object]) -> None:
    destination = Path(path).expanduser().absolute()
    if destination.exists():
        raise FileExistsError("settings output path must not already exist")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    project_root = _require_controlled_project_root(arguments.project_root)
    if arguments.command == "prepare":
        result = prepare_windows_cloud_default_bundle(
            source_directory=arguments.source,
            approval_file=arguments.approval,
            approval_signature_file=arguments.approval_signature,
            delivery_directory=arguments.delivery,
            project_root=project_root,
        )
        print(result.delivery_directory)
        return 0
    if arguments.settings_output:
        runtime_directory = Path(tempfile.mkdtemp(prefix="feetforceplate-r321-"))
        try:
            settings = materialize_validated_windows_cloud_runtime(
                arguments.delivery,
                project_root=project_root,
                runtime_directory=runtime_directory / "resources",
            )
            payload = _settings_payload(settings, runtime_directory=runtime_directory)
            _write_settings_output(arguments.settings_output, payload)
        except Exception:
            shutil.rmtree(runtime_directory, ignore_errors=True)
            raise
    else:
        settings = validate_windows_cloud_default_bundle(
            arguments.delivery, project_root=project_root
        )
        payload = _settings_payload(settings)
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
