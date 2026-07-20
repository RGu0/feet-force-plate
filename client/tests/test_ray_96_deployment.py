from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path, PurePath

from client.app.deployment import (
    ActivationStartupGate,
    AppActivity,
    BuildManifest,
    CandidatePackage,
    DriverStatus,
    RuntimePaths,
    StartupDestination,
    TerminalIdentity,
    UpgradeCoordinator,
    UpgradePolicy,
)


def test_runtime_paths_separate_install_from_persistent_data_and_uninstall_preserves_data() -> None:
    windows = RuntimePaths.for_platform(
        "Windows",
        install_root=PurePath("C:/Program Files/FeetForcePlate"),
        persistent_root=PurePath("C:/ProgramData/FeetForcePlate"),
    )
    macos = RuntimePaths.for_platform(
        "Darwin",
        install_root=PurePath("/Applications/FeetForcePlate.app"),
        persistent_root=PurePath("/Library/Application Support/FeetForcePlate"),
    )

    for paths in (windows, macos):
        assert paths.install_root not in paths.session_segments.parents
        assert paths.session_segments.is_relative_to(paths.persistent_root)
        assert paths.database.is_relative_to(paths.persistent_root)
        assert paths.logs.is_relative_to(paths.persistent_root)
        assert paths.uninstall_preserves == (
            paths.database,
            paths.session_segments,
            paths.logs,
        )


def test_build_manifest_records_software_protocol_report_and_data_schema_versions() -> None:
    manifest = BuildManifest(
        app_version="0.2.0",
        protocol_version="1.0.0-pilot",
        report_schema_version="1.0.0",
        data_schema_version=1,
        minimum_supported_version="0.1.0",
        git_commit="abc1234",
        target="windows-x86_64",
        created_at=datetime(2026, 7, 20, 10, 30, tzinfo=UTC),
    )

    payload = json.loads(manifest.to_json())

    assert payload["app_version"] == "0.2.0"
    assert payload["protocol_version"] == "1.0.0-pilot"
    assert payload["report_schema_version"] == "1.0.0"
    assert payload["data_schema_version"] == 1
    assert "secret" not in manifest.to_json().lower()
    assert "activation_code" not in manifest.to_json().lower()


class _Activation:
    def __init__(self, identity: TerminalIdentity | None) -> None:
        self.identity = identity

    def current_identity(self):
        return self.identity


def test_startup_gate_routes_unactivated_terminal_to_activation_and_bound_terminal_to_workbench() -> None:
    assert (
        ActivationStartupGate(_Activation(None)).destination()
        is StartupDestination.ACTIVATION
    )
    identity = TerminalIdentity("tenant-a", "site-a", "terminal-a")
    assert (
        ActivationStartupGate(_Activation(identity)).destination()
        is StartupDestination.WORKBENCH
    )


class _DriverProbe:
    def __init__(self, status: DriverStatus) -> None:
        self.status = status

    def ch340_status(self) -> DriverStatus:
        return self.status


def test_windows_requires_ch340_probe_but_deployment_layer_does_not_install_driver() -> None:
    policy = UpgradePolicy(
        minimum_supported_version="0.1.0",
        current_data_schema=1,
    )

    assert policy.ch340_readiness("Windows", _DriverProbe(DriverStatus.READY))
    assert not policy.ch340_readiness(
        "Windows",
        _DriverProbe(DriverStatus.MISSING),
    )
    assert policy.ch340_readiness("Darwin", _DriverProbe(DriverStatus.UNKNOWN))


def test_upgrade_rejects_unsigned_incompatible_or_busy_candidates() -> None:
    policy = UpgradePolicy(
        minimum_supported_version="0.1.0",
        current_data_schema=1,
    )
    unsigned = CandidatePackage(
        version="0.2.0",
        signature_verified=False,
        digest_verified=True,
        target_data_schema=1,
        migration_available=True,
    )
    migration_missing = CandidatePackage(
        version="0.2.0",
        signature_verified=True,
        digest_verified=True,
        target_data_schema=2,
        migration_available=False,
    )
    valid = CandidatePackage(
        version="0.2.0",
        signature_verified=True,
        digest_verified=True,
        target_data_schema=2,
        migration_available=True,
    )

    assert not policy.evaluate(unsigned, AppActivity.IDLE).allowed
    assert not policy.evaluate(migration_missing, AppActivity.IDLE).allowed
    assert not policy.evaluate(valid, AppActivity.ACQUIRING).allowed
    assert policy.evaluate(valid, AppActivity.IDLE).allowed


class _Installer:
    def __init__(self) -> None:
        self.events: list[str] = []

    def stage_and_verify(self, candidate) -> str:
        _ = candidate
        self.events.append("stage")
        return "staged-package"

    def activate(self, staged_package: str) -> None:
        _ = staged_package
        self.events.append("activate")
        raise RuntimeError("activation failed")

    def rollback_application(self) -> None:
        self.events.append("rollback-app")


class _Migration:
    def __init__(self) -> None:
        self.events: list[str] = []

    def snapshot_database(self) -> str:
        self.events.append("snapshot-db")
        return "db-snapshot"

    def migrate(self, target_schema: int) -> None:
        _ = target_schema
        self.events.append("migrate")

    def restore_database(self, snapshot: str) -> None:
        _ = snapshot
        self.events.append("restore-db")


def test_failed_upgrade_rolls_back_application_and_database_without_session_data_api() -> None:
    installer = _Installer()
    migration = _Migration()
    coordinator = UpgradeCoordinator(installer=installer, migration=migration)
    candidate = CandidatePackage(
        version="0.2.0",
        signature_verified=True,
        digest_verified=True,
        target_data_schema=2,
        migration_available=True,
    )

    result = coordinator.apply(candidate)

    assert not result.succeeded
    assert installer.events == ["stage", "activate", "rollback-app"]
    assert migration.events == ["snapshot-db", "migrate", "restore-db"]
    assert "delete" not in " ".join(installer.events + migration.events)


def test_pyinstaller_spec_and_build_config_are_present_without_embedded_credentials() -> None:
    root = Path(__file__).parents[1]
    spec = (root / "app" / "packaging" / "FeetForcePlate.spec").read_text(
        encoding="utf-8"
    )
    config = (root / "app" / "packaging" / "build-config.json").read_text(
        encoding="utf-8"
    )

    assert "PySide6" in spec
    assert "windows-x86_64" in config
    assert "macos-universal2-pilot" in config
    assert "private_key" not in (spec + config).lower()
    assert "activation_code" not in (spec + config).lower()
