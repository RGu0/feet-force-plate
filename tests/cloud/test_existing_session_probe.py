from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from pathlib import Path


def _probe_module():
    path = (
        Path(__file__).resolve().parents[2]
        / "scripts"
        / "run_ray269_existing_session_probe.py"
    )
    spec = importlib.util.spec_from_file_location("existing_session_probe", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@dataclass(frozen=True)
class _Session:
    tenant_id: str = "tenant-test"
    account_id: str = "account-test"
    license_id: str = "license-test"
    hardware_asset_id: str = "asset-test"
    hardware_id: str = "asset-serial-test"
    client_installation_id: str = "installation-test"
    access_token: str = "must-not-leak-access-token"
    signed_license: str = "must-not-leak-signed-license"


class _Lease:
    def __init__(self) -> None:
        self.acquired = False
        self.released = False

    def acquire(self):
        self.acquired = True
        return object()

    def release(self, reason: str) -> None:
        assert reason == "RAY-269_ACCEPTANCE_PROBE"
        self.released = True


class _Runtime:
    def __init__(self) -> None:
        self.session = _Session()
        self.lease = _Lease()

    def refresh(self):
        return self.session

    def hardware_lease_lifecycle(self, session: _Session):
        assert session is self.session
        return self.lease

    def close(self) -> None:
        pass


def test_probe_refreshes_then_releases_a_lease_without_serializing_credentials() -> None:
    module = _probe_module()
    runtime = _Runtime()

    result = module.run_probe(runtime)

    assert result == {
        "schema_version": "ray269-existing-session-probe/1",
        "license_refresh_verified": True,
        "lease_acquired": True,
        "lease_released": True,
        "secrets_or_identifiers_included": False,
    }
    assert runtime.lease.acquired is True
    assert runtime.lease.released is True
