#!/usr/bin/env python3
"""Issue or query protected-offline Windows cloud delivery approvals."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from client.cloud.controlled_delivery_signer import (  # noqa: E402
    issue_approval_pair,
    query_audit,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    sign = commands.add_parser("sign")
    sign.add_argument("--request", type=Path, required=True)
    sign.add_argument("--signer-policy", type=Path, required=True)
    sign.add_argument("--source", type=Path, required=True)
    sign.add_argument("--project-root", type=Path, required=True)
    sign.add_argument("--output", type=Path, required=True)
    audit = commands.add_parser("audit")
    audit.add_argument("--signer-policy", type=Path, required=True)
    audit.add_argument("--target-commit", required=True)
    return parser


def _require_controlled_project_root(project_root: Path) -> Path:
    candidate = Path(project_root).expanduser().resolve()
    if candidate != PROJECT_ROOT.resolve():
        raise ValueError("ProjectRoot must be the controlled source root")
    return candidate


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "sign":
            issued = issue_approval_pair(
                request_file=arguments.request,
                policy_file=arguments.signer_policy,
                source_directory=arguments.source,
                project_root=_require_controlled_project_root(arguments.project_root),
                output_directory=arguments.output,
            )
            print(issued.output_directory)
            return 0
        records = query_audit(
            policy_file=arguments.signer_policy, target_commit=arguments.target_commit
        )
        for record in records:
            print(json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        return 0
    except (FileExistsError, ValueError) as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
