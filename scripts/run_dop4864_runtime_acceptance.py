"""Run a local-only DO-P4864 hardware runtime acceptance capture.

The command deliberately uses the production hardware composition rather than a
parser-only recorder: a qualifying empty-board baseline is followed by a
duration-bounded acquisition, quality gate, encrypted valid-session commit and
a fresh-process-equivalent recovery scan.  It never uploads data and writes no
raw matrices or AES key material into the JSON summary.

The key file is an acceptance-only stand-in for the future provisioned terminal
key.  It is local, mode 0600 and intentionally outside repository evidence.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import uuid

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from client.device.acquisition import ConnectionStateMachine, LatestFrameMailbox
from client.device.protocol import DaoOneP4864Parser, ProtocolProfile, RawFrame
from client.device.serial_transport import SerialByteTransport
from client.device.session_runtime import HardwareSessionRuntime
from client.device.transport import TransportDisconnected
from client.hardware_standardization.baseline import build_baseline_reference
from client.hardware_standardization.do_p4864 import DoP4864StandardizationAdapter
from client.hardware_standardization.models import BaselineSample, UnloadedBaselineWindow
from client.hardware_standardization.quality import DoP4864HardwareQualityGate
from client.spool.recovery import RecoveryScanner
from client.spool.session_commit import ValidSessionStager
from client.spool.state_store import SensitiveBlobCodec, StateStore


class FileAesKeyProvider:
    """Acceptance-only local AES-256 key holder; production provisioning is separate."""

    def __init__(self, key_file: Path) -> None:
        self._key_file = key_file

    def get_key(self) -> bytes:
        if self._key_file.exists():
            key = self._key_file.read_bytes()
            if len(key) != 32:
                raise ValueError("acceptance AES key file must contain exactly 32 bytes")
            return key
        self._key_file.parent.mkdir(parents=True, exist_ok=True)
        key = os.urandom(32)
        descriptor = os.open(
            self._key_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600
        )
        try:
            os.write(descriptor, key)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return key


def _profile() -> ProtocolProfile:
    return ProtocolProfile.observed_compact_8bit(
        version="do-p4864/observed-compact-column-major-48x64-20260721"
    )


def _collect_baseline(
    *, device: str, duration_ns: int, maximum_no_valid_signal_ns: int
) -> tuple[tuple[RawFrame, ...], dict[str, int]]:
    parser = DaoOneP4864Parser(_profile())
    specification = DoP4864StandardizationAdapter.observed_compact_8bit().specification
    transport = SerialByteTransport.open(
        device,
        timeout_seconds=0.5,
        baud_rate=specification.serial_baud_rate,
        data_bits=specification.serial_data_bits,
        parity=specification.serial_parity,
        stop_bits=specification.serial_stop_bits,
    )
    frames: list[RawFrame] = []
    first_ns: int | None = None
    last_valid_signal_ns = time.monotonic_ns()
    try:
        while first_ns is None or frames[-1].host_monotonic_ns - first_ns < duration_ns:
            chunk = transport.read(16_384)
            if not chunk:
                if time.monotonic_ns() - last_valid_signal_ns >= maximum_no_valid_signal_ns:
                    raise RuntimeError("baseline received no valid decoded signal within the device limit")
                continue
            decoded = parser.feed(chunk)
            for frame in decoded:
                if first_ns is None:
                    first_ns = frame.host_monotonic_ns
                frames.append(frame)
                last_valid_signal_ns = time.monotonic_ns()
    except TransportDisconnected as exc:
        raise RuntimeError(f"baseline transport disconnected: {exc}") from exc
    finally:
        transport.close()
    return tuple(frames), {
        "decoded_frames": parser.statistics.valid_frames,
        "checksum_observations": parser.statistics.checksum_observations,
        "checksum_mismatches": parser.statistics.checksum_mismatches,
        "invalid_frames": parser.statistics.invalid_frames,
        "resynchronizations": parser.statistics.resynchronizations,
    }


def _baseline_reference(
    frames: tuple[RawFrame, ...], *, maximum_empty_count: float, minimum_duration_ns: int
):
    if len(frames) < 2:
        raise RuntimeError("baseline did not contain at least two frames")
    values = np.stack([frame.values.reshape(-1, order="F") for frame in frames])
    cell_median = np.median(values, axis=0)
    if float(cell_median.max()) > maximum_empty_count:
        raise RuntimeError(
            "baseline is not unloaded: cell median exceeds empty-board threshold"
        )
    source = hashlib.sha256()
    for frame in frames:
        source.update(frame.host_monotonic_ns.to_bytes(8, "big", signed=False))
        source.update(frame.values.tobytes(order="F"))
    adapter = DoP4864StandardizationAdapter.observed_compact_8bit()
    window = UnloadedBaselineWindow(
        schema_version="unloaded-baseline-window/1",
        baseline_window_id=str(uuid.uuid4()),
        validation_run_id=str(uuid.uuid4()),
        validation_outcome="PASS",
        layout_digest=adapter.layout.digest,
        rules_version="do-p4864-unloaded-baseline/1",
        threshold_version="do-p4864-quality/1",
        source_digest=source.hexdigest(),
        samples=tuple(
            BaselineSample(
                host_monotonic_ns=frame.host_monotonic_ns,
                values=tuple(int(value) for value in frame.values.reshape(-1, order="F")),
            )
            for frame in frames
        ),
    )
    return build_baseline_reference(window, minimum_duration_ns=minimum_duration_ns), {
        "frames": len(frames),
        "duration_seconds": window.duration_ns / 1_000_000_000,
        "maximum_cell_median_count": float(cell_median.max()),
        "source_sha256": window.source_digest,
    }


def _safe_acquisition_reason_code(reason: str | None) -> str | None:
    """Collapse transport/runtime detail before emitting acceptance evidence."""

    if reason is None:
        return None
    normalized = reason.lower()
    if "transport disconnected" in normalized or "serial" in normalized:
        return "TRANSPORT_DISCONNECTED"
    if "no valid" in normalized or "signal" in normalized:
        return "SIGNAL_UNAVAILABLE"
    return "ACQUISITION_INVALID"


def run_acceptance(args: argparse.Namespace) -> dict[str, object]:
    specification = DoP4864StandardizationAdapter.observed_compact_8bit().specification
    minimum_baseline_seconds = specification.baseline_min_duration_s
    if args.baseline_seconds is None:
        args.baseline_seconds = minimum_baseline_seconds
    if args.baseline_seconds < minimum_baseline_seconds:
        raise ValueError("baseline-seconds must meet the selected device specification")
    if args.capture_seconds <= 0:
        raise ValueError("capture-seconds must be positive")
    if args.serial_timeout_seconds <= 0:
        raise ValueError("serial-timeout-seconds must be positive")
    root = args.output_root.resolve()
    spool_root = root / "spool"
    key_provider = FileAesKeyProvider(args.key_file.resolve())
    baseline_frames, baseline_parser = _collect_baseline(
        device=args.device,
        duration_ns=round(args.baseline_seconds * 1_000_000_000),
        maximum_no_valid_signal_ns=round(
            specification.startup_validation.maximum_no_valid_signal_s * 1_000_000_000
        ),
    )
    baseline, baseline_summary = _baseline_reference(
        baseline_frames,
        maximum_empty_count=args.maximum_empty_count,
        minimum_duration_ns=round(minimum_baseline_seconds * 1_000_000_000),
    )
    store = StateStore(root / "state.sqlite3", SensitiveBlobCodec(key_provider))
    session_id = str(uuid.uuid4())
    try:
        store.put_subject_ref("hardware-acceptance-no-subject", b"local-only")
        stager = ValidSessionStager(
            spool_root,
            session_id=session_id,
            key_provider=key_provider,
            store=store,
            subject_uuid="hardware-acceptance-no-subject",
            consent_id=None,
            versions={
                "protocol": _profile().version,
                "quality": "quality-policy/do-p4864-mvp/1",
                "runtime_acceptance": "do-p4864-runtime-acceptance/1",
                "serial_read_timeout_ms": str(
                    round(args.serial_timeout_seconds * 1_000)
                ),
            },
            started_at_ns=time.time_ns(),
        )
        connection = ConnectionStateMachine()
        connection.start_connecting()
        connection.mark_ready()
        parser = DaoOneP4864Parser(_profile())
        transport = SerialByteTransport.open(
            args.device,
            timeout_seconds=args.serial_timeout_seconds,
            baud_rate=specification.serial_baud_rate,
            data_bits=specification.serial_data_bits,
            parity=specification.serial_parity,
            stop_bits=specification.serial_stop_bits,
        )
        try:
            result = HardwareSessionRuntime(
                transport=transport,
                parser=parser,
                connection=connection,
                mailbox=LatestFrameMailbox(),
                stager=stager,
                quality_gate=DoP4864HardwareQualityGate(baseline_reference=baseline),
                storage_append_timeout_s=args.storage_append_timeout_seconds,
            ).capture(
                session_id=session_id,
                minimum_duration_ns=round(args.capture_seconds * 1_000_000_000),
            )
        finally:
            transport.close()
        store.close()
        restarted = StateStore(root / "state.sqlite3", SensitiveBlobCodec(key_provider))
        try:
            recovery = RecoveryScanner(
                spool_root / "sessions", restarted, key_provider, spool_root
            ).scan(recovered_at_ns=time.time_ns())
            status = restarted.session_status(session_id) if result.committed else None
            artifact_count = len(restarted.session_artifacts(session_id)) if result.committed else 0
        finally:
            restarted.close()
    finally:
        try:
            store.close()
        except Exception:
            pass
    return {
        "schema_version": "do-p4864-runtime-acceptance-result/1",
        "captured_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "requested_baseline_seconds": args.baseline_seconds,
        "requested_capture_seconds": args.capture_seconds,
        "baseline": {**baseline_summary, "parser": baseline_parser},
        "runtime": {
            "outcome": result.acquisition.outcome.value,
            "frames_stored": result.acquisition.frames_stored,
            "reason_code": _safe_acquisition_reason_code(result.reason),
            "validity": result.validity.value,
            "committed": result.committed,
            "communication_integrity": {
                "policy_version": "do-p4864-valid-signal-continuity/1",
                "maximum_no_valid_signal_ns": round(
                    specification.startup_validation.maximum_no_valid_signal_s
                    * 1_000_000_000
                ),
                "reconstructed_frame_count": len(
                    result.acquisition.reconstructed_frames
                ),
                "events": [
                    {
                        "event_index": event.event_index,
                        "failure_kind": event.failure_kind,
                        "invalid_frame_count": event.invalid_frame_count,
                        "discarded_bytes": event.discarded_bytes,
                        "preceding_source_index": event.preceding_source_index,
                        "following_source_index": event.following_source_index,
                        "valid_signal_gap_ns": event.valid_signal_gap_ns,
                        "reconstructed_frame_count": event.reconstructed_frame_count,
                        "resolution": event.resolution,
                    }
                    for event in result.acquisition.integrity_events
                ],
            },
            "parser": {
                "valid_frames": parser.statistics.valid_frames,
                "invalid_frames": parser.statistics.invalid_frames,
                "resynchronizations": parser.statistics.resynchronizations,
                "length_failures": parser.statistics.length_failures,
                "function_failures": parser.statistics.function_failures,
                "tail_failures": parser.statistics.tail_failures,
                "checksum_mismatches": parser.statistics.checksum_mismatches,
            },
        },
        "post_restart": {
            "session_status": status,
            "derived_artifact_count": artifact_count,
            "recovery": asdict(recovery),
        },
        "local_only_boundary": "Raw and derived encrypted data remain under output-root; this summary contains no raw matrices, device paths, AES key material, or runtime exception text.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument(
        "--key-file",
        type=Path,
        default=Path("/private/tmp/feetforceplate-runtime-acceptance.aes256"),
    )
    parser.add_argument("--baseline-seconds", type=float)
    parser.add_argument("--capture-seconds", type=float, default=600.0)
    parser.add_argument("--maximum-empty-count", type=float, default=5.0)
    parser.add_argument("--serial-timeout-seconds", type=float, default=0.25)
    parser.add_argument("--storage-append-timeout-seconds", type=float, default=2.0)
    parser.add_argument(
        "--summary-output",
        type=Path,
        help="optional sanitized summary path; use a separate volume when testing storage exhaustion",
    )
    args = parser.parse_args()
    exit_code = 0
    try:
        result = run_acceptance(args)
        if not result["runtime"]["committed"]:
            exit_code = 2
    except Exception as exc:
        exit_code = 2
        result = {
            "schema_version": "do-p4864-runtime-acceptance-result/1",
            "captured_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "requested_baseline_seconds": args.baseline_seconds,
            "requested_capture_seconds": args.capture_seconds,
            "runtime": {
                "outcome": "INVALID",
                "frames_stored": None,
                "reason": f"acceptance runner failed: {type(exc).__name__}",
                "validity": "INVALID",
                "committed": False,
            },
            "local_only_boundary": "Failure summary contains no raw matrices, key material, or exception text.",
        }
    summary = args.summary_output or args.output_root / "runtime-acceptance-summary.json"
    summary.parent.mkdir(parents=True, exist_ok=True)
    summary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
