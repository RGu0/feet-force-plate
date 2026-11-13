"""RAY-447 R7: the pre-foundation safe-event log is verified once and archived unchanged."""

from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid5

import pytest

from client.support import SafeClientEvent, SafeClientEventStore, safe_events
from client.support.diagnostic_export import _revalidate_records
from client.support.legacy_safe_event_chain import (
    LEGACY_DIRECTORY_NAME,
    _legacy_record_digest,
)
from techflex_cloud_foundation.contracts.client_sync import canonical_json_bytes

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


def _foundation_events_file(directory: Path, count: int) -> bytes:
    """A real new-format events.jsonl, produced by the store itself."""

    store = SafeClientEventStore(directory)
    for index in range(count):
        store.append(_event(200 + index))
    return (directory / "events.jsonl").read_bytes()


def test_diagnostic_export_verification_accepts_the_chain_after_migration(tmp_path: Path) -> None:
    root = tmp_path / "safe-events"
    _write_legacy_log(root, (2,))
    store = SafeClientEventStore(root)
    for index in range(3):
        store.append(_event(100 + index))

    records = _revalidate_records(store.verified_records())  # raised before the fix

    assert [record.event for record in records] == [_event(100 + index) for index in range(3)]
    # the first surviving record is a segment start; every later link is still checked
    tampered = list(store.verified_records())
    tampered[2] = tampered[2].model_copy(update={"previous_sha256": "1" * 64})
    with pytest.raises(ValueError, match="strict verification"):
        _revalidate_records(tuple(tampered))
    tampered = list(store.verified_records())
    tampered[0] = tampered[0].model_copy(update={"sha256": "0" * 64})
    with pytest.raises(ValueError, match="strict verification"):
        _revalidate_records(tuple(tampered))


def test_a_damaged_first_line_is_archived_with_the_rest_and_nothing_is_cut(tmp_path: Path) -> None:
    root = tmp_path / "safe-events"
    written, _ = _write_legacy_log(root, (2, 2))
    # newest generation: first line garbled, last record complete but without its newline
    damaged = b"not json at all\n" + written["events.jsonl"].splitlines(keepends=True)[1].rstrip(b"\n")
    (root / "events.jsonl").write_bytes(damaged)

    store = SafeClientEventStore(root)  # must open, not raise

    archive = root / LEGACY_DIRECTORY_NAME
    assert (archive / "events.jsonl").read_bytes() == damaged  # not truncated by anyone
    assert (archive / "events.1.jsonl").read_bytes() == written["events.1.jsonl"]
    (anchor,) = store.anchors()
    assert anchor["legacy_verified"] is False and anchor["legacy_failure"] == "INVALID_RECORD"
    store.append(_event(100))
    assert [r.event for r in store.verified_records()] == [_event(100)]


def test_a_mixed_set_of_generations_is_archived_whole(tmp_path: Path) -> None:
    root = tmp_path / "mixed"
    written, _ = _write_legacy_log(root, (2,))
    (root / "events.1.jsonl").write_bytes(written["events.jsonl"])  # old format, older generation
    (root / "events.jsonl").write_bytes(_foundation_events_file(tmp_path / "scratch", 2))
    before = {name: (root / name).read_bytes() for name in ("events.1.jsonl", "events.jsonl")}

    store = SafeClientEventStore(root)

    for name, data in before.items():
        assert (root / LEGACY_DIRECTORY_NAME / name).read_bytes() == data
    (anchor,) = store.anchors()
    assert anchor["legacy_verified"] is False  # a mixed set is not one verifiable chain
    store.append(_event(100))
    assert len(store.verified_records()) == 1


def test_an_empty_current_file_beside_old_generations_is_harmless(tmp_path: Path) -> None:
    root = tmp_path / "safe-events"
    written, head = _write_legacy_log(root, (2,))
    (root / "events.1.jsonl").write_bytes(written["events.jsonl"])
    (root / "events.jsonl").write_bytes(b"")

    store = SafeClientEventStore(root)

    assert (root / LEGACY_DIRECTORY_NAME / "events.1.jsonl").read_bytes() == written["events.jsonl"]
    (anchor,) = store.anchors()
    assert anchor["legacy_verified"] is True and anchor["legacy_head_sha256"] == head


def test_the_anchor_is_written_once_even_after_it_rotates_out_of_retention(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(safe_events, "MAX_GENERATION_BYTES", 900)
    root = tmp_path / "safe-events"
    _write_legacy_log(root, (2,))
    store = SafeClientEventStore(root)
    for index in range(40):  # far past three small generations: the anchor is gone
        store.append(_event(100 + index))
    assert store.anchors() == ()
    assert (root / LEGACY_DIRECTORY_NAME / ".anchored").exists()
    size_before = sum(path.stat().st_size for path in root.glob("events*.jsonl"))

    for _ in range(5):
        reopened = SafeClientEventStore(root)

    assert reopened.anchors() == ()  # no fresh anchor on any later open
    assert sum(path.stat().st_size for path in root.glob("events*.jsonl")) == size_before


def test_the_marker_is_written_after_the_anchor_and_a_stop_between_them_heals(
    tmp_path: Path,
) -> None:
    root = tmp_path / "safe-events"
    _write_legacy_log(root, (1,))
    SafeClientEventStore(root)
    (root / LEGACY_DIRECTORY_NAME / ".anchored").unlink()  # the stop: anchor written, no marker

    healed = SafeClientEventStore(root)

    assert len(healed.anchors()) == 1  # not anchored a second time
    assert (root / LEGACY_DIRECTORY_NAME / ".anchored").exists()


def test_a_wrong_link_between_old_generations_fails_the_verification(tmp_path: Path) -> None:
    root = tmp_path / "safe-events"
    written, _ = _write_legacy_log(root, (2, 2))
    first_of_newest, _ = _legacy_line(_event(50), "2" * 64)  # links to a digest nobody has
    (root / "events.jsonl").write_bytes(first_of_newest + b"".join(
        written["events.jsonl"].splitlines(keepends=True)[1:]
    ))

    (anchor,) = SafeClientEventStore(root).anchors()

    assert anchor["legacy_failure"] == "BROKEN_CHAIN" and anchor["legacy_verified"] is False
    assert anchor["legacy_record_count"] == 2  # the verified older generation only


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_the_archive_directory_is_private(tmp_path: Path) -> None:
    root = tmp_path / "safe-events"
    _write_legacy_log(root, (1,))

    SafeClientEventStore(root)

    assert (root / LEGACY_DIRECTORY_NAME).stat().st_mode & 0o777 == 0o700


def _open_store_in_process(root_text: str, results: object) -> None:
    try:
        SafeClientEventStore(root_text)
        results.put("ok")  # type: ignore[attr-defined]
    except BaseException as exc:  # reported to the parent, which fails the test
        results.put(f"{type(exc).__name__}: {exc}")  # type: ignore[attr-defined]


def test_simultaneous_first_starts_neither_crash_nor_lose_the_old_log(tmp_path: Path) -> None:
    root = tmp_path / "safe-events"
    written, head = _write_legacy_log(root, (2, 3))
    context = multiprocessing.get_context("spawn")
    results = context.Queue()
    workers = [
        context.Process(target=_open_store_in_process, args=(str(root), results))
        for _ in range(6)
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=30)
        assert worker.exitcode == 0
    outcomes = [results.get(timeout=5) for _ in workers]

    assert outcomes == ["ok"] * 6
    for name, data in written.items():
        assert (root / LEGACY_DIRECTORY_NAME / name).read_bytes() == data
    store = SafeClientEventStore(root)
    anchors = store.anchors()
    assert anchors and all(a["legacy_head_sha256"] == head for a in anchors)  # chain reads fine


def test_a_file_another_process_already_moved_is_skipped_not_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "safe-events"
    written, _ = _write_legacy_log(root, (2,))
    stale_listing = tuple(root / name for name in written)  # what this process saw first
    archive = root / LEGACY_DIRECTORY_NAME
    archive.mkdir()
    for name in written:  # ... and the other process has finished moving them since
        (root / name).replace(archive / name)
    monkeypatch.setattr(safe_events, "legacy_chain_files", lambda _root: stale_listing)

    assert safe_events._archive_legacy_chain(root) is False  # nothing left for us; no error

    assert (archive / "events.jsonl").read_bytes() == written["events.jsonl"]


def test_a_torn_first_line_beside_a_healthy_foundation_chain_is_not_archived(tmp_path: Path) -> None:
    root = tmp_path / "safe-events"
    store = SafeClientEventStore(root)
    for index in range(2):
        store.append(_event(index))
    healthy = (root / "events.jsonl").read_bytes()
    (root / "events.1.jsonl").write_bytes(healthy)
    (root / "events.jsonl").write_bytes(b'{"payload":{"sch')  # crash in the first append after rotation

    reopened = SafeClientEventStore(root)

    assert not (root / LEGACY_DIRECTORY_NAME).exists()
    assert reopened.anchors() == ()
    assert (root / "events.1.jsonl").read_bytes() == healthy
    SafeClientEventStore(root)  # a second open after the same crash must still start
    assert not (root / LEGACY_DIRECTORY_NAME).exists()


def test_a_file_that_vanishes_during_the_move_is_skipped_not_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "safe-events"
    _write_legacy_log(root, (2,))
    real_replace = os.replace

    def vanishing_replace(source: Path, target: Path) -> None:
        if Path(source).name == "events.jsonl":
            real_replace(source, Path(target).parent.parent / "elsewhere.jsonl")  # the other process won
            raise FileNotFoundError(source)
        real_replace(source, target)

    monkeypatch.setattr(safe_events.os, "replace", vanishing_replace)

    assert safe_events._archive_legacy_chain(root) in {True, False}  # no exception is the point
    assert not (root / "events.jsonl").exists()


def test_an_unreadable_new_chain_does_not_stop_the_start_when_the_marker_is_missing(
    tmp_path: Path,
) -> None:
    root = tmp_path / "safe-events"
    _write_legacy_log(root, (2,))
    store = SafeClientEventStore(root)
    store.append(_event(1))
    store.append(_event(2))
    (root / LEGACY_DIRECTORY_NAME / ".anchored").unlink()  # a stop before the marker was written
    lines = (root / "events.jsonl").read_bytes().splitlines(keepends=True)
    row = json.loads(lines[-1])
    row["sha256"] = "0" * 64
    lines[-1] = json.dumps(row).encode() + b"\n"  # first line intact, a later digest wrong
    damaged = b"".join(lines)
    (root / "events.jsonl").write_bytes(damaged)

    SafeClientEventStore(root)  # must open; reading reports the fault, the constructor does not

    assert (root / LEGACY_DIRECTORY_NAME / ".anchored").exists()
    assert (root / "events.jsonl").read_bytes() == damaged  # nothing chained on top of it


def test_a_lone_file_with_a_terminated_garbled_first_line_is_still_archived(tmp_path: Path) -> None:
    root = tmp_path / "safe-events"
    written, _ = _write_legacy_log(root, (2,))
    damaged = b"not json at all\n" + written["events.jsonl"].splitlines(keepends=True)[1]
    (root / "events.jsonl").write_bytes(damaged)

    store = SafeClientEventStore(root)

    assert (root / LEGACY_DIRECTORY_NAME / "events.jsonl").read_bytes() == damaged
    (anchor,) = store.anchors()
    assert anchor["legacy_verified"] is False


def test_a_whitespace_only_file_beside_a_healthy_foundation_chain_is_not_archived(
    tmp_path: Path,
) -> None:
    root = tmp_path / "safe-events"
    store = SafeClientEventStore(root)
    store.append(_event(1))
    healthy = (root / "events.jsonl").read_bytes()
    (root / "events.1.jsonl").write_bytes(healthy)
    (root / "events.jsonl").write_bytes(b"  ")

    SafeClientEventStore(root)

    assert not (root / LEGACY_DIRECTORY_NAME).exists()
    assert (root / "events.1.jsonl").read_bytes() == healthy


def test_two_processes_writing_the_marker_at_once_do_not_collide(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "safe-events"
    (root / LEGACY_DIRECTORY_NAME).mkdir(parents=True)
    real_replace = os.replace
    interleaved: list[bool] = []

    def replace_after_the_other_process_finished(source: object, target: object) -> None:
        if not interleaved:  # the other process runs its whole marker write first
            interleaved.append(True)
            safe_events._mark_legacy_anchored(root)
        real_replace(source, target)

    monkeypatch.setattr(os, "replace", replace_after_the_other_process_finished)

    safe_events._mark_legacy_anchored(root)  # raised FileNotFoundError with a shared staging name

    assert (root / LEGACY_DIRECTORY_NAME / ".anchored").read_bytes() == b"anchored\n"
    assert [p.name for p in (root / LEGACY_DIRECTORY_NAME).iterdir()] == [".anchored"]
