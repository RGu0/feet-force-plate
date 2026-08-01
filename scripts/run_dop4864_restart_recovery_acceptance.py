"""Exercise controlled DO-P4864 process interruption and startup recovery.

The child uses the normal local-only hardware acceptance composition.  This
parent intentionally kills that child while it is still capturing, then opens a
fresh state store and runs the same recovery scanner used at startup.  The JSON
summary contains only process/recovery aggregates; encrypted raw data and the
AES key remain outside repository evidence.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from client.spool.recovery import RecoveryScanner
from client.spool.state_store import SensitiveBlobCodec, StateStore
from client.hardware_standardization.do_p4864 import DoP4864StandardizationAdapter
from scripts.run_dop4864_runtime_acceptance import FileAesKeyProvider


def _formal_storage_counts(database_path: Path) -> dict[str, int]:
    connection = sqlite3.connect(database_path)
    try:
        return {
            label: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for label, table in {
                "sessions": "sessions",
                "segments": "segments",
                "artifacts": "session_artifacts",
            }.items()
        }
    finally:
        connection.close()


def recover_after_interruption(root: Path, key_file: Path) -> dict[str, object]:
    """Run one fresh-process recovery and return a raw-free evidence payload."""

    key_provider = FileAesKeyProvider(key_file.resolve())
    store = StateStore(root / "state.sqlite3", SensitiveBlobCodec(key_provider))
    try:
        recovery = RecoveryScanner(
            root / "spool" / "sessions", store, key_provider, root / "spool"
        ).scan(recovered_at_ns=time.time_ns())
    finally:
        store.close()
    return {
        "recovery": asdict(recovery),
        "formal_storage": _formal_storage_counts(root / "state.sqlite3"),
    }


def _capture_command(args: argparse.Namespace, root: Path) -> list[str]:
    runtime_script = Path(__file__).with_name("run_dop4864_runtime_acceptance.py")
    return [
        sys.executable,
        str(runtime_script),
        "--device",
        args.device,
        "--output-root",
        str(root),
        "--key-file",
        str(args.key_file.resolve()),
        "--baseline-seconds",
        str(args.baseline_seconds),
        "--capture-seconds",
        str(args.capture_seconds),
    ]


def run_controlled_restart(args: argparse.Namespace) -> dict[str, object]:
    specification = DoP4864StandardizationAdapter.observed_compact_8bit().specification
    if args.baseline_seconds is None:
        args.baseline_seconds = specification.baseline_min_duration_s
    if args.baseline_seconds < specification.baseline_min_duration_s:
        raise ValueError("baseline-seconds must meet the selected device specification")
    if args.interrupt_after_seconds <= args.baseline_seconds:
        raise ValueError("interrupt-after-seconds must allow capture time after baseline")
    root = args.output_root.resolve()
    if root.exists() and any(root.iterdir()):
        raise ValueError("output-root must be empty for a controlled restart test")
    root.mkdir(parents=True, exist_ok=True)
    command = _capture_command(args, root)
    child = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    interrupted = False
    try:
        return_code = child.wait(timeout=args.interrupt_after_seconds)
    except subprocess.TimeoutExpired:
        child.kill()
        return_code = child.wait(timeout=10)
        interrupted = True

    restart = recover_after_interruption(root, args.key_file)
    recovery = restart["recovery"]
    assert isinstance(recovery, dict)
    formal_storage = restart["formal_storage"]
    assert isinstance(formal_storage, dict)
    passed = (
        interrupted
        and int(recovery["interrupted_staging_discarded"]) >= 1
        and formal_storage == {"sessions": 0, "segments": 0, "artifacts": 0}
    )
    return {
        "schema_version": "do-p4864-controlled-restart-recovery/1",
        "captured_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "requested_baseline_seconds": args.baseline_seconds,
        "requested_capture_seconds": args.capture_seconds,
        "requested_interrupt_after_seconds": args.interrupt_after_seconds,
        "process": {
            "forced_interruption": interrupted,
            "child_return_code": return_code,
        },
        **restart,
        "passed": passed,
        "local_only_boundary": "The child capture and key remain under output-root/private storage; this summary contains no raw matrices, identities, key material, or child output.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--key-file", type=Path, required=True)
    parser.add_argument("--baseline-seconds", type=float)
    parser.add_argument("--capture-seconds", type=float, default=180.0)
    parser.add_argument("--interrupt-after-seconds", type=float, default=25.0)
    parser.add_argument("--summary-output", type=Path)
    args = parser.parse_args()
    if args.capture_seconds <= args.interrupt_after_seconds:
        parser.error("capture-seconds must exceed interrupt-after-seconds")
    result = run_controlled_restart(args)
    summary_path = args.summary_output or args.output_root / "restart-recovery-summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
