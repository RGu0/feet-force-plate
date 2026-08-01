from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2] / "deploy/aliyun/seed"


def test_backup_is_custom_format_manifested_encrypted_and_atomically_published() -> None:
    text = (ROOT / "backup.sh").read_text()
    for token in (
        "pg_dump", "--format=custom", "sha256sum", "object-manifest.sha256",
        "FEETFORCEPLATE_BACKUP_AGE_RECIPIENT", "age --recipient", ".staging-",
        "sync -f", "mv ", "implementation_sha", "schema_versions",
    ):
        assert token in text
    assert "AGE_RECIPIENT=" not in text
    assert "PRIVATE_KEY" not in text


def test_retention_preserves_newest_verified_backup() -> None:
    text = (ROOT / "backup.sh").read_text()
    assert "newest_bundle" in text
    assert "candidate" in text
    assert '"$candidate" == "$newest_bundle"' in text
    assert "RETENTION_DAYS" in text


def test_restore_requires_separate_empty_targets_and_verifies_objects() -> None:
    text = (ROOT / "restore-verify.sh").read_text()
    for token in (
        "FEETFORCEPLATE_RESTORE_DSN", "FEETFORCEPLATE_BACKUP_DSN",
        "FEETFORCEPLATE_RESTORE_OBJECT_ROOT", "FEETFORCEPLATE_OBJECT_ROOT",
        "target database must be empty", "target object root must be empty",
        "pg_restore", "sha256sum --check", "object-manifest.sha256",
        "FEETFORCEPLATE_BACKUP_AGE_IDENTITY_FILE",
    ):
        assert token in text
    assert "--clean" not in text


def test_daily_systemd_timer_and_service_are_present() -> None:
    service = (ROOT / "feetforceplate-backup.service").read_text()
    timer = (ROOT / "feetforceplate-backup.timer").read_text()
    assert "User=feetforceplate" in service
    assert "ExecStart=/opt/feetforceplate/app/deploy/aliyun/seed/backup.sh" in service
    assert "ReadWritePaths=/var/lib/feetforceplate/backups" in service
    assert "OnCalendar=daily" in timer
    assert "Persistent=true" in timer
