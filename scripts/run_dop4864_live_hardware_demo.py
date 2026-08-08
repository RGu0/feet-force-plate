"""Run the supervised, local-only real-hardware demonstration workflow.

It captures one anonymous, four-stage static-balance session from the connected
DO-P4864 board, commits only a hardware-valid session, then requests the
supervising operator's stage confirmations before it can create a nondiagnostic
basic PDF report.  It never uploads data.  A negative or absent confirmation
keeps the capture but suppresses the report.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
import time
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from client.hardware_integration.live_hardware_demo import (
    build_operator_attested_protocol,
    is_basic_report_eligible,
    operator_attestations_from_completion_flags,
    static_balance_stage_plan,
)
from client.device.acquisition import ConnectionStateMachine, LatestFrameMailbox
from client.device.protocol import DaoOneP4864Parser
from client.device.serial_transport import SerialByteTransport
from client.device.session_runtime import HardwareSessionRuntime
from client.hardware_standardization.do_p4864 import DoP4864StandardizationAdapter
from client.hardware_standardization.quality import DoP4864HardwareQualityGate
from client.local_analysis.service import process_committed_physical_session
from client.reporting.pdf import BasicReportPdfRenderer
from client.spool.session_commit import ValidSessionStager
from client.spool.state_store import SensitiveBlobCodec, StateStore
from cloud.analysis.feature_parameters import FeatureParameters
from scripts.run_dop4864_runtime_acceptance import (
    FileAesKeyProvider,
    _baseline_reference,
    _collect_baseline,
    _profile,
)


_STAGE_GUIDANCE = (
    "双脚站立、睁眼、自然放松",
    "双脚站立、闭眼；全程由现场人员看护",
    "半串联站立：左脚在前；全程由现场人员看护",
    "半串联站立：右脚在前；全程由现场人员看护",
)


def _confirm_stage_completions(plan, *, input_func=input) -> tuple[bool, ...]:
    confirmations: list[bool] = []
    for index, (stage, guidance) in enumerate(zip(plan, _STAGE_GUIDANCE), start=1):
        answer = input_func(
            f"确认第 {index} 段（{guidance}）已在现场看护下完整完成，"
            "且无扶栏、协助、失衡或提前睁眼？[y/N] "
        ).strip().lower()
        confirmations.append(answer in {"y", "yes"})
    return tuple(confirmations)


def run_live_demo(args: argparse.Namespace) -> dict[str, object]:
    if not args.supervised:
        raise ValueError("--supervised is required for the live hardware demo")
    if args.stage_seconds < 10.0:
        raise ValueError("stage-seconds must be at least 10 seconds")
    output_root = args.output_root.resolve()
    key_file = args.key_file.resolve()
    if key_file.is_relative_to(output_root):
        raise ValueError("key-file must be outside output-root")
    specification = DoP4864StandardizationAdapter.observed_compact_8bit().specification
    baseline_seconds = args.baseline_seconds or specification.baseline_min_duration_s
    if baseline_seconds < specification.baseline_min_duration_s:
        raise ValueError("baseline-seconds must meet the device specification")

    print("现场人员须持续看护。发生不适、失衡或需要扶持时，请立即中止。")
    plan = static_balance_stage_plan(stage_seconds=args.stage_seconds)
    for index, guidance in enumerate(_STAGE_GUIDANCE, start=1):
        print(f"第 {index} 段 {args.stage_seconds:.0f}s：{guidance}")

    baseline_frames, _baseline_parser = _collect_baseline(
        device=args.device,
        duration_ns=round(baseline_seconds * 1_000_000_000),
        maximum_no_valid_signal_ns=round(
            specification.startup_validation.maximum_no_valid_signal_s * 1_000_000_000
        ),
    )
    baseline, baseline_summary = _baseline_reference(
        baseline_frames,
        maximum_empty_count=args.maximum_empty_count,
        minimum_duration_ns=round(specification.baseline_min_duration_s * 1_000_000_000),
    )

    output_root.mkdir(parents=True, exist_ok=True)
    key_provider = FileAesKeyProvider(key_file)
    store = StateStore(output_root / "state.sqlite3", SensitiveBlobCodec(key_provider))
    session_id = str(uuid4())
    captured_at = datetime.now(UTC)
    result = None
    try:
        store.put_subject_ref("live-demo-anonymous", b"anonymous-local-demo")
        stager = ValidSessionStager(
            output_root / "spool",
            session_id=session_id,
            key_provider=key_provider,
            store=store,
            subject_uuid="live-demo-anonymous",
            consent_id=None,
            versions={
                "protocol": _profile().version,
                "quality": "quality-policy/do-p4864-mvp/1",
                "live_demo": "do-p4864-supervised-local-demo/1",
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
                minimum_duration_ns=round(4 * args.stage_seconds * 1_000_000_000),
            )
        finally:
            transport.close()

        summary: dict[str, object] = {
            "schema_version": "do-p4864-live-hardware-demo/1",
            "captured_at_utc": captured_at.isoformat(),
            "requested_stage_seconds": args.stage_seconds,
            "baseline": {
                "frames": baseline_summary["frames"],
                "duration_seconds": baseline_summary["duration_seconds"],
            },
            "hardware": {
                "outcome": result.acquisition.outcome.value,
                "frames_stored": result.acquisition.frames_stored,
                "validity": result.validity.value,
                "committed": result.committed,
            },
            "report_generated": False,
            "local_only_boundary": (
                "The session and report remain local. No account, cloud upload, "
                "clinical diagnosis, risk score, or personal identity is included."
            ),
        }
        if not result.committed:
            return summary

        confirmations = (
            (False, False, False, False)
            if args.noninteractive
            else _confirm_stage_completions(plan)
        )
        context = build_operator_attested_protocol(
            session_id=session_id,
            stage_seconds=args.stage_seconds,
            attestations=operator_attestations_from_completion_flags(plan, confirmations),
        )
        summary["operator_attested_all_stages"] = is_basic_report_eligible(context)
        if not is_basic_report_eligible(context):
            return summary

        outcome = process_committed_physical_session(
            output_root / "spool",
            session_id=session_id,
            store=store,
            key_provider=key_provider,
            protocol_context=context,
            parameters=FeatureParameters(
                version="physical-features/live-hardware-demo/1",
            ),
            report_id=f"live-demo-{uuid4().hex[:12]}",
            report_version=1,
            analysis_result_id=f"live-analysis-{uuid4().hex[:12]}",
            subject_display_id=args.subject_display_id,
            captured_at=captured_at,
            generated_at=datetime.now(UTC),
        )
        report_path = args.report_output or output_root / "live-hardware-basic-report.pdf"
        from PySide6.QtWidgets import QApplication

        application = QApplication.instance() or QApplication([])
        _ = application
        BasicReportPdfRenderer().render(outcome.report, report_path)
        summary["report_generated"] = True
        summary["report_path"] = str(report_path)
        return summary
    finally:
        store.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--key-file", type=Path, required=True)
    parser.add_argument("--report-output", type=Path)
    parser.add_argument("--subject-display-id", default="现场匿名演示")
    parser.add_argument("--baseline-seconds", type=float)
    parser.add_argument("--stage-seconds", type=float, default=20.0)
    parser.add_argument("--maximum-empty-count", type=float, default=5.0)
    parser.add_argument("--serial-timeout-seconds", type=float, default=0.25)
    parser.add_argument("--storage-append-timeout-seconds", type=float, default=2.0)
    parser.add_argument("--noninteractive", action="store_true")
    parser.add_argument("--supervised", action="store_true")
    parser.add_argument("--summary-output", type=Path)
    args = parser.parse_args(argv)
    try:
        summary = run_live_demo(args)
        exit_code = 0 if summary["report_generated"] else 2
    except Exception as exc:
        summary = {
            "schema_version": "do-p4864-live-hardware-demo/1",
            "hardware": {"committed": False},
            "report_generated": False,
            "failure_code": type(exc).__name__,
            "local_only_boundary": "Failure summary contains no raw matrices or key material.",
        }
        exit_code = 2
    destination = args.summary_output or args.output_root / "live-hardware-demo-summary.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
