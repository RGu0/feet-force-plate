"""One-time archive of the pre-foundation safe-event log (RAY-447 R7).

Before foundation's ``ChainedAppendLog`` the client kept its own hash-chained
log in the same directory and with the same file names, but with a different
line format (``{"schema_version", "event", "previous_sha256", "sha256"}``
instead of ``{"payload", "previous_sha256", "sha256"}``).  foundation cannot
read those lines, so on the first start after the upgrade the old chain is
verified once with the rules it was written under, moved unchanged into
``legacy/`` (never deleted), and a new foundation chain starts with an anchor
record that carries the old chain's head digest and length.

This module exists only for that migration and can be deleted once no
installation can still hold an old-format log.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

from pydantic import ValidationError

from shared.contracts.client_sync import canonical_json_bytes

LEGACY_DIRECTORY_NAME = "legacy"
LEGACY_GENERATION_FILENAMES = ("events.2.jsonl", "events.1.jsonl", "events.jsonl")


@dataclass(frozen=True, slots=True)
class LegacyChainSummary:
    """What the one-time verification found; safe to store in an anchor record."""

    verified: bool
    failure: str | None
    record_count: int
    first_sha256: str | None
    head_sha256: str | None
    truncated_tail: bool
    file_names: tuple[str, ...]


def legacy_chain_files(root: Path) -> tuple[Path, ...]:
    """Generation files in ``root`` to archive, oldest first; empty when none.

    foundation reads (and on open "repairs") only its own line format, so a
    file it would not recognise must never be left for it.  The test is
    therefore by exclusion: a non-empty generation file whose first line is
    not a foundation record (``payload`` key) is old-format or damaged and
    triggers the archive.  When any file does, every non-empty generation file
    goes into the archive together, so a mixed or half-moved set cannot leave
    foundation a chain whose older half it cannot link.
    """

    present = [
        root / name
        for name in LEGACY_GENERATION_FILENAMES
        if (root / name).is_file() and (root / name).stat().st_size
    ]
    if any(_first_line_kind(path) != "foundation" for path in present):
        return tuple(present)
    return ()


def verify_legacy_chain(directory: Path) -> LegacyChainSummary:
    """Verify the archived old chain exactly as the old store did, oldest first.

    An incomplete final line of the newest file is a crash remnant the old
    store used to cut away on open; it is ignored and reported, not an error.
    """

    from client.support.safe_events import SafeClientLogRecord  # noqa: PLC0415

    names: list[str] = []
    count = 0
    first: str | None = None
    previous: str | None = None
    truncated = False
    paths = [directory / name for name in LEGACY_GENERATION_FILENAMES if (directory / name).is_file()]
    for index, path in enumerate(paths):
        names.append(path.name)
        data = path.read_bytes()
        lines = data.splitlines()
        if index == len(paths) - 1 and data and not data.endswith(b"\n") and lines:
            try:
                json.loads(lines[-1].decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                lines = lines[:-1]
                truncated = True
        for raw_line in lines:
            if not raw_line:
                return _summary(False, "EMPTY_RECORD", count, first, previous, truncated, names)
            try:
                record = SafeClientLogRecord.model_validate_json(raw_line)
            except (ValueError, ValidationError):
                return _summary(False, "INVALID_RECORD", count, first, previous, truncated, names)
            if previous is not None and record.previous_sha256 != previous:
                return _summary(False, "BROKEN_CHAIN", count, first, previous, truncated, names)
            if record.sha256 != _legacy_record_digest(record.event, record.previous_sha256):
                return _summary(False, "INVALID_DIGEST", count, first, previous, truncated, names)
            first = first or record.sha256
            previous = record.sha256
            count += 1
    return _summary(True, None, count, first, previous, truncated, names)


def _summary(
    verified: bool,
    failure: str | None,
    count: int,
    first: str | None,
    head: str | None,
    truncated: bool,
    names: list[str],
) -> LegacyChainSummary:
    return LegacyChainSummary(verified, failure, count, first, head, truncated, tuple(names))


def _legacy_record_digest(event: object, previous_sha256: str | None) -> str:
    previous_digest_bytes = bytes.fromhex(previous_sha256) if previous_sha256 else b""
    return hashlib.sha256(canonical_json_bytes(event) + previous_digest_bytes).hexdigest()


def _first_line_kind(path: Path) -> str:
    """``foundation`` for a foundation record, ``other`` for anything else."""

    try:
        with path.open("rb") as handle:
            for raw_line in handle:
                if not raw_line.strip():
                    continue
                decoded = json.loads(raw_line.decode("utf-8"))
                if isinstance(decoded, dict) and "payload" in decoded and "event" not in decoded:
                    return "foundation"
                return "other"
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return "other"
    return "other"
