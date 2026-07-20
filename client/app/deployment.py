from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import PurePath
from typing import Protocol


@dataclass(frozen=True, slots=True)
class RuntimePaths:
    install_root: PurePath
    persistent_root: PurePath
    database: PurePath
    session_segments: PurePath
    logs: PurePath
    config_cache: PurePath
    uninstall_preserves: tuple[PurePath, ...]

    @classmethod
    def for_platform(
        cls,
        platform_name: str,
        *,
        install_root: PurePath,
        persistent_root: PurePath,
    ) -> RuntimePaths:
        if platform_name not in {"Windows", "Darwin"}:
            raise ValueError(f"unsupported packaging platform: {platform_name}")
        database = persistent_root / "database" / "client.sqlite3"
        segments = persistent_root / "sessions" / "encrypted-segments"
        logs = persistent_root / "logs"
        return cls(
            install_root=install_root,
            persistent_root=persistent_root,
            database=database,
            session_segments=segments,
            logs=logs,
            config_cache=persistent_root / "config-cache",
            uninstall_preserves=(database, segments, logs),
        )


@dataclass(frozen=True, slots=True)
class BuildManifest:
    app_version: str
    protocol_version: str
    report_schema_version: str
    data_schema_version: int
    minimum_supported_version: str
    git_commit: str
    target: str
    created_at: datetime

    def to_json(self) -> str:
        return json.dumps(
            {
                "app_version": self.app_version,
                "protocol_version": self.protocol_version,
                "report_schema_version": self.report_schema_version,
                "data_schema_version": self.data_schema_version,
                "minimum_supported_version": self.minimum_supported_version,
                "git_commit": self.git_commit,
                "target": self.target,
                "created_at": self.created_at.isoformat(),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )


@dataclass(frozen=True, slots=True)
class TerminalIdentity:
    tenant_id: str
    site_id: str
    terminal_id: str


class ActivationPort(Protocol):
    def current_identity(self) -> TerminalIdentity | None: ...


class StartupDestination(StrEnum):
    ACTIVATION = "ACTIVATION"
    WORKBENCH = "WORKBENCH"


class ActivationStartupGate:
    def __init__(self, activation: ActivationPort) -> None:
        self._activation = activation

    def destination(self) -> StartupDestination:
        identity = self._activation.current_identity()
        if identity is None:
            return StartupDestination.ACTIVATION
        if not all(
            value.strip()
            for value in (
                identity.tenant_id,
                identity.site_id,
                identity.terminal_id,
            )
        ):
            return StartupDestination.ACTIVATION
        return StartupDestination.WORKBENCH


class DriverStatus(StrEnum):
    READY = "READY"
    MISSING = "MISSING"
    UNKNOWN = "UNKNOWN"


class DriverProbePort(Protocol):
    def ch340_status(self) -> DriverStatus: ...


class AppActivity(StrEnum):
    IDLE = "IDLE"
    ACQUIRING = "ACQUIRING"
    FINALIZING = "FINALIZING"
    REPORTING = "REPORTING"


@dataclass(frozen=True, slots=True)
class CandidatePackage:
    version: str
    signature_verified: bool
    digest_verified: bool
    target_data_schema: int
    migration_available: bool


@dataclass(frozen=True, slots=True)
class UpgradeDecision:
    allowed: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class UpgradePolicy:
    minimum_supported_version: str
    current_data_schema: int

    def ch340_readiness(
        self,
        platform_name: str,
        probe: DriverProbePort,
    ) -> bool:
        if platform_name != "Windows":
            return True
        return probe.ch340_status() is DriverStatus.READY

    def evaluate(
        self,
        candidate: CandidatePackage,
        activity: AppActivity,
    ) -> UpgradeDecision:
        reasons: list[str] = []
        if not candidate.signature_verified:
            reasons.append("SIGNATURE_NOT_VERIFIED")
        if not candidate.digest_verified:
            reasons.append("DIGEST_NOT_VERIFIED")
        if _version_tuple(candidate.version) < _version_tuple(
            self.minimum_supported_version
        ):
            reasons.append("VERSION_BELOW_MINIMUM")
        if activity is not AppActivity.IDLE:
            reasons.append("APPLICATION_BUSY")
        if (
            candidate.target_data_schema != self.current_data_schema
            and not candidate.migration_available
        ):
            reasons.append("MIGRATION_NOT_AVAILABLE")
        return UpgradeDecision(not reasons, tuple(reasons))


class InstallerPort(Protocol):
    def stage_and_verify(self, candidate: CandidatePackage) -> str: ...

    def activate(self, staged_package: str) -> None: ...

    def rollback_application(self) -> None: ...


class MigrationPort(Protocol):
    def snapshot_database(self) -> str: ...

    def migrate(self, target_schema: int) -> None: ...

    def restore_database(self, snapshot: str) -> None: ...


@dataclass(frozen=True, slots=True)
class UpgradeResult:
    succeeded: bool
    error_code: str | None = None


class UpgradeCoordinator:
    def __init__(
        self,
        *,
        installer: InstallerPort,
        migration: MigrationPort,
    ) -> None:
        self._installer = installer
        self._migration = migration

    def apply(self, candidate: CandidatePackage) -> UpgradeResult:
        database_snapshot: str | None = None
        try:
            staged = self._installer.stage_and_verify(candidate)
            database_snapshot = self._migration.snapshot_database()
            self._migration.migrate(candidate.target_data_schema)
            self._installer.activate(staged)
        except Exception:
            self._installer.rollback_application()
            if database_snapshot is not None:
                self._migration.restore_database(database_snapshot)
            return UpgradeResult(False, "E-UPD-001")
        return UpgradeResult(True)


def _version_tuple(value: str) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in value.split("."))
    except ValueError as exc:
        raise ValueError(f"invalid semantic version: {value}") from exc
