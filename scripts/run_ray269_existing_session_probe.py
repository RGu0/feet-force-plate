#!/usr/bin/env python3
"""Verify a stored test session without exposing its credentials or identity."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from client.cloud.access_store import ClientAccessStore, KeyringCredentialStore
from client.cloud.runtime import AccessRuntimeSettings, build_client_access_runtime


def run_probe(runtime) -> dict[str, object]:
    """Refresh the signed License, briefly lease the asset, then release it."""

    session = runtime.refresh()
    lease = runtime.hardware_lease_lifecycle(session)
    lease.acquire()
    lease.release("RAY-269_ACCEPTANCE_PROBE")
    status = getattr(getattr(lease, "state", None), "status", None)
    status_value = getattr(status, "value", status)
    return {
        "schema_version": "ray269-existing-session-probe/1",
        "license_refresh_verified": True,
        "lease_acquired": True,
        "lease_released": status_value in (None, "RELEASED"),
        "secrets_or_identifiers_included": False,
    }


def _stored_license_key_id(data_root: Path) -> str:
    store = ClientAccessStore(
        data_root / "database" / "access.sqlite3", KeyringCredentialStore()
    )
    try:
        state = store.load()
        if state is None:
            raise RuntimeError("no stored institution session is available")
        return state.signed_license.key_id
    finally:
        store.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--ca-file", type=Path, required=True)
    parser.add_argument("--license-public-key-file", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    runtime = None
    try:
        settings = AccessRuntimeSettings._from_values(
            raw_url=args.base_url,
            integration_mode=True,
            ca_bundle=str(args.ca_file),
            license_key_id=_stored_license_key_id(args.data_root),
            public_key_file=args.license_public_key_file,
        )
        runtime = build_client_access_runtime(settings, data_root=args.data_root)
        result = run_probe(runtime)
        exit_code = 0 if result["lease_released"] else 2
    except Exception as exc:
        result = {
            "schema_version": "ray269-existing-session-probe/1",
            "license_refresh_verified": False,
            "lease_acquired": False,
            "lease_released": False,
            "secrets_or_identifiers_included": False,
            "failure_category": type(exc).__name__,
        }
        exit_code = 2
    finally:
        if runtime is not None:
            runtime.close()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
