#!/usr/bin/env python3
"""Prepare or validate a public-only Windows cloud-default delivery."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from client.cloud.windows_bundle import (  # noqa: E402
    prepare_windows_cloud_default_bundle,
    validate_windows_cloud_default_bundle,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--source", type=Path, required=True)
    prepare.add_argument("--approval", type=Path, required=True)
    prepare.add_argument("--delivery", type=Path, required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("--delivery", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if arguments.command == "prepare":
        result = prepare_windows_cloud_default_bundle(
            source_directory=arguments.source,
            approval_file=arguments.approval,
            delivery_directory=arguments.delivery,
        )
        print(result.delivery_directory)
        return 0
    settings = validate_windows_cloud_default_bundle(arguments.delivery)
    print(
        json.dumps(
            {
                "api_base_url": settings.base_url,
                "ca_bundle": str(settings.ca_bundle),
                "integration_mode": settings.integration_mode,
                "license_key_id": settings.license_key_id,
                "license_public_key_file": str(settings.license_public_key),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
