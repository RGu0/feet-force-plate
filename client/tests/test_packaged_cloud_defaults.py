from __future__ import annotations

import json
import runpy
import shutil
from pathlib import Path

import pytest

from client.cloud.packaged_defaults import stage_packaged_cloud_defaults
from client.cloud.packaged_defaults import load_packaged_cloud_defaults
from client.cloud.runtime import AccessRuntimeSettings


def _write_public_bundle(
    directory: Path,
    *,
    channel: str = "integration",
    api_base_url: str = "https://39.105.216.113:7443",
    license_key_id: str = "license/2-key-1",
    public_key: bytes = b"p" * 32,
) -> None:
    directory.mkdir()
    (directory / "cloud-default.json").write_text(
        json.dumps(
            {
                "schema_version": "feetforceplate-client-cloud-default/1",
                "channel": channel,
                "api_base_url": api_base_url,
                "license_key_id": license_key_id,
                "ca_bundle_resource": "cloud-ca.pem",
                "license_public_key_resource": "license-public.key",
            }
        ),
        encoding="utf-8",
    )
    (directory / "cloud-ca.pem").write_text("public test CA", encoding="utf-8")
    (directory / "license-public.key").write_bytes(public_key)


@pytest.mark.parametrize(
    "public_key",
    [b" " + b"p" * 31, b"p" * 31 + b"\n"],
    ids=["leading-space-byte", "trailing-newline-byte"],
)
def test_loader_accepts_exact_32_raw_public_key_bytes_before_text_normalization(
    tmp_path: Path, public_key: bytes
) -> None:
    """Catches the production loader stripping binary key bytes first."""

    source = tmp_path / "public-bundle"
    _write_public_bundle(source, public_key=public_key)

    defaults = load_packaged_cloud_defaults(source)

    assert defaults is not None
    assert defaults.license_public_key.read_bytes() == public_key


@pytest.mark.parametrize(
    ("api_base_url", "license_key_id"),
    [
        ("https://39.105.216.113:7443\nspoofed", "license/2-key-1"),
        ("https://39.105.216.113:7443", "license/2-key-1\rspoofed"),
        ("https://39.105.216.113:7443", "license/one\u2028spoofed"),
        ("https://39.105.216.113:7443", "license/one\u2029spoofed"),
    ],
    ids=["api-base-url", "license-key-id", "line-separator", "paragraph-separator"],
)
def test_loader_rejects_unsafe_unicode_in_public_metadata(
    tmp_path: Path, api_base_url: str, license_key_id: str
) -> None:
    """Catches packaged metadata that can inject terminal or log lines."""

    source = tmp_path / "public-bundle"
    _write_public_bundle(
        source,
        api_base_url=api_base_url,
        license_key_id=license_key_id,
    )

    with pytest.raises(ValueError, match="unsafe characters"):
        load_packaged_cloud_defaults(source)


def test_loader_accepts_printable_unicode_license_key_id(tmp_path: Path) -> None:
    """Printable Unicode remains valid metadata when it cannot split output."""

    source = tmp_path / "public-bundle"
    _write_public_bundle(source, license_key_id="license/授权-✓")

    defaults = load_packaged_cloud_defaults(source)

    assert defaults is not None
    assert defaults.license_key_id == "license/授权-✓"


def test_public_integration_bundle_stages_at_fixed_names_and_becomes_runtime_default(
    tmp_path: Path,
) -> None:
    source = tmp_path / "server-export-with-arbitrary-name"
    _write_public_bundle(source)
    staged = tmp_path / "package-resources"

    stage_packaged_cloud_defaults(source, staged)
    settings = AccessRuntimeSettings.from_environment(
        {}, packaged_resource_root=staged
    )

    assert settings is not None
    assert settings.base_url == "https://39.105.216.113:7443"
    assert settings.integration_mode is True
    assert settings.verify == str(staged / "cloud-ca.pem")
    assert settings.license_public_key_file == staged / "license-public.key"
    assert (staged / "cloud-default.json").is_file()
    assert str(source) not in (staged / "cloud-default.json").read_text(
        encoding="utf-8"
    )


def test_distribution_bundle_rejects_the_self_signed_integration_port(
    tmp_path: Path,
) -> None:
    source = tmp_path / "invalid-distribution-bundle"
    _write_public_bundle(source, channel="distribution")

    with pytest.raises(ValueError, match="distribution"):
        stage_packaged_cloud_defaults(source, tmp_path / "package-resources")


def test_spec_stages_public_cloud_bundle_without_source_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "server-release-input"
    _write_public_bundle(source)
    captured: dict[str, object] = {}

    class _Analysis:
        def __init__(self, *_args, **kwargs) -> None:
            captured["datas"] = kwargs["datas"]
            self.pure = []
            self.scripts = []
            self.binaries = []
            self.datas = []

    monkeypatch.setenv("FEETFORCEPLATE_CLOUD_DEFAULT_DIRECTORY", str(source))
    monkeypatch.delenv("FEETFORCEPLATE_SUPPORT_RECIPIENT_FILE", raising=False)
    monkeypatch.setattr("sys.platform", "linux")
    spec = Path(__file__).parents[1] / "app" / "packaging" / "FeetForcePlate.spec"
    workpath = tmp_path / "pyinstaller-work"
    runpy.run_path(
        str(spec),
        init_globals={
            "SPECPATH": str(spec.parent),
            "workpath": str(workpath),
            "Analysis": _Analysis,
            "PYZ": lambda *_args: object(),
            "EXE": lambda *_args, **_kwargs: object(),
            "COLLECT": lambda *_args, **_kwargs: object(),
        },
    )

    cloud_data = [
        item for item in captured["datas"] if item[1] == "client/app/resources"
    ]
    assert {Path(item[0]).name for item in cloud_data} >= {
        "cloud-default.json",
        "cloud-ca.pem",
        "license-public.key",
    }
    artifact = tmp_path / "onedir" / "client/app/resources"
    artifact.mkdir(parents=True)
    for staged_source, _destination in cloud_data:
        shutil.copyfile(staged_source, artifact / Path(staged_source).name)
    settings = AccessRuntimeSettings.from_environment(
        {}, packaged_resource_root=artifact
    )
    assert settings is not None
    assert str(source) not in json.dumps(captured, default=str)
