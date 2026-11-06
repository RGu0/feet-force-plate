"""RAY-447 R7: the pre-foundation safe-event log is verified once and archived unchanged."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid5

import pytest

from client.support import SafeClientEvent, SafeClientEventStore
from client.support.legacy_safe_event_chain import (
    LEGACY_DIRECTORY_NAME,
    _legacy_record_digest,
)
from shared.contracts.client_sync import canonical_json_bytes

_NAMESPACE = UUID("00000000-0000-0000-0000-0000000000a7")
_INSTALLATION = UUID("00000000-0000-0000-0000-0000000000b8")


def _event(index: int) -> SafeClientEvent:
    return SafeClientEvent(
        event_id=uuid5(_NAMESPACE, f"event-{index}"),
        occurred_at=datetime(2026, 11, 5, 12, 0, tzinfo=UTC) + timedelta(seconds=index),
        name="APPLICATION_STARTED",
        outcome="OK",
        client_installation_id=_INSTALLATION,
        app_version="1.0.0",
        protocol_version="p1",
        data_mode_version="d1",
        config_version="c1",
    )


def _legacy_line(event: SafeClientEvent, previous: str | None) -> tuple[bytes, str]:
    """One line exactly as the pre-foundation store wrote it."""

    digest = _legacy_record_digest(event, previous)
    record = {
        "schema_version": "safe-client-log-record/1",
        "event": json.loads(canonical_json_bytes(event)),
        "previous_sha256": previous,
        "sha256": digest,
    }
    return json.dumps(record, sort_keys=True, separators=(",", ":")).encode() + b"\n", digest


def _write_legacy_log(root: Path, per_file: tuple[int, ...]) -> tuple[dict[str, bytes], str]:
    """Write an old-format log over generation files; returns file bytes and head digest."""

    names = ("events.2.jsonl", "events.1.jsonl", "events.jsonl")[-len(per_file):]
    root.mkdir(parents=True, exist_ok=True)
    previous: str | None = None
    written: dict[str, bytes] = {}
    index = 0
    for name, count in zip(names, per_file, strict=True):
        data = b""
        for _ in range(count):
            line, previous = _legacy_line(_event(index), previous)
            data += line
            index += 1
        (root / name).write_bytes(data)
        written[name] = data
    assert previous is not None
    return written, previous


def test_an_old_log_is_verified_archived_unchanged_and_a_new_chain_starts(tmp_path: Path) -> None:
    root = tmp_path / "safe-events"
    written, head = _write_legacy_log(root, (2, 3))

    store = SafeClientEventStore(root)

    archive = root / LEGACY_DIRECTORY_NAME
    for name, data in written.items():
        assert (archive / name).read_bytes() == data  # byte for byte
    (anchor,) = store.anchors()
    assert anchor["schema_version"] == "safe-client-log-anchor/1"
    assert anchor["legacy_verified"] is True and anchor["legacy_failure"] is None
    assert anchor["legacy_record_count"] == 5
    assert anchor["legacy_head_sha256"] == head
    assert anchor["legacy_files"] == ["events.1.jsonl", "events.jsonl"]
    assert store.verified_records() == ()  # an anchor is not an event

    store.append(_event(100))
    (record,) = store.verified_records()
    assert record.event == _event(100)
    assert record.previous_sha256 is not None  # chained to the anchor
    assert store.anchors() == (anchor,)


def test_opening_again_neither_archives_nor_anchors_twice(tmp_path: Path) -> None:
    root = tmp_path / "safe-events"
    _write_legacy_log(root, (2,))
    SafeClientEventStore(root).append(_event(100))
    before = sorted(path.name for path in (root / LEGACY_DIRECTORY_NAME).iterdir())

    reopened = SafeClientEventStore(root)

    assert len(reopened.anchors()) == 1
    assert [r.event for r in reopened.verified_records()] == [_event(100)]
    assert sorted(path.name for path in (root / LEGACY_DIRECTORY_NAME).iterdir()) == before


@pytest.mark.parametrize("damage", ["digest", "link"])
def test_an_old_log_that_fails_verification_is_archived_unchanged_and_flagged(
    tmp_path: Path, damage: str
) -> None:
    root = tmp_path / "safe-events"
    written, _ = _write_legacy_log(root, (3,))
    lines = written["events.jsonl"].splitlines()
    row = json.loads(lines[1])
    if damage == "digest":
        row["sha256"] = "0" * 64
    else:
        row["previous_sha256"] = "1" * 64
    tampered = b"\n".join([lines[0], json.dumps(row, sort_keys=True).encode(), lines[2]]) + b"\n"
    (root / "events.jsonl").write_bytes(tampered)

    store = SafeClientEventStore(root)

    assert (root / LEGACY_DIRECTORY_NAME / "events.jsonl").read_bytes() == tampered
    (anchor,) = store.anchors()
    assert anchor["legacy_verified"] is False
    assert anchor["legacy_failure"] in {"INVALID_DIGEST", "BROKEN_CHAIN"}
    assert anchor["legacy_record_count"] == 1  # only the records verified before the break
    store.append(_event(100))  # the new chain works regardless
    assert len(store.verified_records()) == 1


def test_a_torn_final_line_of_the_old_log_is_ignored_and_reported(tmp_path: Path) -> None:
    root = tmp_path / "safe-events"
    written, head = _write_legacy_log(root, (2,))
    torn = written["events.jsonl"] + b'{"schema_version":"safe-client-log-record/1","ev'
    (root / "events.jsonl").write_bytes(torn)

    store = SafeClientEventStore(root)

    assert (root / LEGACY_DIRECTORY_NAME / "events.jsonl").read_bytes() == torn
    (anchor,) = store.anchors()
    assert anchor["legacy_verified"] is True
    assert anchor["legacy_truncated_tail"] is True
    assert anchor["legacy_record_count"] == 2 and anchor["legacy_head_sha256"] == head


def test_a_stop_between_archiving_and_anchoring_is_completed_on_the_next_open(
    tmp_path: Path,
) -> None:
    root = tmp_path / "safe-events"
    written, head = _write_legacy_log(root, (2,))
    archive = root / LEGACY_DIRECTORY_NAME
    archive.mkdir()
    (root / "events.jsonl").replace(archive / "events.jsonl")  # the files moved, then a crash

    store = SafeClientEventStore(root)

    (anchor,) = store.anchors()
    assert anchor["legacy_head_sha256"] == head and anchor["legacy_record_count"] == 2
    assert (archive / "events.jsonl").read_bytes() == written["events.jsonl"]
    assert len(SafeClientEventStore(root).anchors()) == 1


def test_it_refuses_to_overwrite_an_existing_archive(tmp_path: Path) -> None:
    root = tmp_path / "safe-events"
    written, _ = _write_legacy_log(root, (1,))
    archive = root / LEGACY_DIRECTORY_NAME
    archive.mkdir()
    (archive / "events.jsonl").write_bytes(b"older archive\n")

    with pytest.raises(RuntimeError, match="refusing to overwrite"):
        SafeClientEventStore(root)

    assert (root / "events.jsonl").read_bytes() == written["events.jsonl"]  # not moved
    assert (archive / "events.jsonl").read_bytes() == b"older archive\n"  # not replaced


def test_a_fresh_or_already_migrated_directory_gets_no_archive_and_no_anchor(
    tmp_path: Path,
) -> None:
    root = tmp_path / "safe-events"

    store = SafeClientEventStore(root)
    store.append(_event(1))
    reopened = SafeClientEventStore(root)

    assert not (root / LEGACY_DIRECTORY_NAME).exists()
    assert reopened.anchors() == ()
    assert [r.event for r in reopened.verified_records()] == [_event(1)]


def test_new_records_are_in_the_foundation_line_format(tmp_path: Path) -> None:
    root = tmp_path / "safe-events"
    store = SafeClientEventStore(root)
    store.append(_event(1))

    row = json.loads((root / "events.jsonl").read_text(encoding="utf-8").splitlines()[0])

    assert set(row) == {"payload", "previous_sha256", "sha256"}
    assert row["payload"]["schema_version"] == "safe-client-event/1"
    assert hashlib.sha256(
        json.dumps(row["payload"], sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest() == row["sha256"]
