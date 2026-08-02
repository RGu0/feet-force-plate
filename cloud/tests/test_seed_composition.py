from __future__ import annotations

import base64
import asyncio
import os
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat
from httpx import ASGITransport, AsyncClient

from cloud.api.seed import SeedSettings
from cloud.api.seed import build_seed_app
from cloud.api.seed import serve_seed


def _values(root: Path) -> dict[str, str]:
    private = Ed25519PrivateKey.generate().private_bytes(
        Encoding.Raw, PrivateFormat.Raw, NoEncryption()
    )
    return {
        "migration_dsn": "postgresql://migration@127.0.0.1/ffp",
        "tenant_dsn": "postgresql://tenant@127.0.0.1/ffp",
        "activation_dsn": "postgresql://activation@127.0.0.1/ffp",
        "platform_dsn": "postgresql://platform@127.0.0.1/ffp",
        "tenant_token_secret": "t" * 40,
        "platform_token_secret": "p" * 40,
        "tenant_refresh_hmac_key": "r" * 40,
        "platform_refresh_hmac_key": "q" * 40,
        "tenant_login_hmac_key": "l" * 40,
        "platform_login_hmac_key": "m" * 40,
        "activation_hmac_key": "a" * 40,
        "identity_lookup_hmac_key": "i" * 40,
        "identity_encryption_key_b64": base64.b64encode(os.urandom(32)).decode(),
        "license_private_key_b64": base64.b64encode(private).decode(),
        "license_key_id": "license/2-seed",
        "object_root": str(root),
        "public_base_url": "https://seed.example.test:7443",
        "trusted_proxies": ("127.0.0.1",),
    }


def test_settings_accept_separate_roles_and_private_external_object_root() -> None:
    with TemporaryDirectory(dir="/private/tmp") as directory:
        settings = SeedSettings(**_values(Path(directory)))
        assert settings.public_base_url.startswith("https://")
        assert settings.tenant_dsn != settings.platform_dsn


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("tenant_dsn", "sqlite:///tmp/ffp.db", "PostgreSQL"),
        ("tenant_token_secret", "short", "32"),
        ("public_base_url", "http://seed.example.test:7443", "HTTPS"),
    ],
)
def test_settings_reject_unsafe_values(field: str, value: str, message: str) -> None:
    with TemporaryDirectory(dir="/private/tmp") as directory:
        values = _values(Path(directory))
        values[field] = value
        with pytest.raises(ValueError, match=message):
            SeedSettings(**values)


def test_settings_reject_shared_tenant_platform_secrets() -> None:
    with TemporaryDirectory(dir="/private/tmp") as directory:
        values = _values(Path(directory))
        values["platform_token_secret"] = values["tenant_token_secret"]
        with pytest.raises(ValueError, match="distinct"):
            SeedSettings(**values)


def test_settings_reject_object_root_inside_repository() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    with pytest.raises(ValueError, match="outside"):
        SeedSettings(**_values(repository_root / "tmp-objects"))


def test_settings_reject_secret_file_broader_than_0600() -> None:
    with TemporaryDirectory(dir="/private/tmp") as directory:
        root = Path(directory)
        secret_file = root / "seed.env"
        secret_file.write_text("FEETFORCEPLATE_TEST=redacted\n")
        secret_file.chmod(0o640)
        values = _values(root / "objects")
        values["secret_file"] = secret_file
        with pytest.raises(ValueError, match="0600"):
            SeedSettings(**values)


class _Acquire:
    def __init__(self, pool):
        self.pool = pool

    async def __aenter__(self):
        return self.pool

    async def __aexit__(self, *_args):
        return None


class _ReadyPool:
    def __init__(self):
        self.loop = asyncio.get_running_loop()

    def acquire(self):
        return _Acquire(self)

    async def fetchval(self, query: str):
        assert asyncio.get_running_loop() is self.loop
        assert query == "SELECT 1"
        return 1

    async def close(self):
        return None


def test_build_composes_only_seed_identity_and_data_plane_services() -> None:
    async def exercise() -> None:
        with TemporaryDirectory(dir="/private/tmp") as directory:
            settings = SeedSettings(**_values(Path(directory) / "objects"))

            async def pool_factory(**_kwargs):
                return _ReadyPool()

            app = await build_seed_app(settings, pool_factory=pool_factory)
            services = app.state.services
            assert services.tenant_access is not None
            assert services.platform_access is not None
            assert services.ingestion is not None
            assert services.heartbeats is not None
            assert services.devices is None
            assert services.operations is None
            assert services.token_issuer is None
            assert services.operations_tokens is None

    asyncio.run(exercise())


def test_server_and_postgres_pools_share_one_event_loop() -> None:
    async def exercise() -> None:
        with TemporaryDirectory(dir="/private/tmp") as directory:
            settings = SeedSettings(**_values(Path(directory) / "objects"))

            async def pool_factory(**_kwargs):
                return _ReadyPool()

            class InspectingServer:
                def __init__(self, config):
                    self.config = config

                async def serve(self) -> None:
                    async with AsyncClient(
                        transport=ASGITransport(app=self.config.app),
                        base_url="http://seed.test",
                    ) as client:
                        response = await client.get("/health/ready")
                    assert response.status_code == 200
                    assert response.json()["dependencies"] == {
                        "postgres": "ready",
                        "object_store": "ready",
                    }

            await serve_seed(
                settings,
                pool_factory=pool_factory,
                server_factory=InspectingServer,
            )

    asyncio.run(exercise())
