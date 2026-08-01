"""Runnable local-only V1 replay composition; it deliberately has no network client."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QPushButton

from client.app.controller import ApplicationController
from client.app.app_icon import application_icon
from client.app.fixture_replay import (
    FixtureReplayAcquisition,
    FixtureReplayBootstrap,
    FixtureReplaySource,
    StandardizedReplaySource,
    UnavailableFixtureReplaySource,
)
from client.app.local_store import LocalReplayStore
from client.app.live_display import LiveDisplayProjection
from client.app.ui_integration import build_connected_ui
from client.hardware_standardization.live_processing import (
    replay_debug_profile,
)
from client.hardware_standardization.runtime import active_hardware_runtime
from client.app.heatmap import PhysicalGridOverlay
from client.local_analysis.display import DisplayRefreshController, LatestDisplayFrameMailbox
from client.local_analysis.v1_debug import V1ReplayDebugProcessor
from client.reporting.delivery import ReportDeliveryService
from client.reporting.pdf import BasicReportPdfRenderer
from client.workflow.consent import ConsentPolicy, ConsentWorkflow
from client.workflow.protocol import (
    FeatureFlags,
    ProtocolCatalog,
    ProtocolParadigm,
    default_standard_protocol,
)


class _Telemetry:
    def record_error(self, **kwargs): _ = kwargs


class _Print:
    def print_pdf(self, pdf_path, *, job_name): _ = pdf_path, job_name


@dataclass(frozen=True, slots=True)
class LocalReplayRuntime:
    """The shared, strictly local composition root for replay and verification."""

    source: object
    acquisition: FixtureReplayAcquisition
    store: LocalReplayStore
    controller: ApplicationController


def parse_replay_arguments(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="FeetForcePlate 本地 V1 回放调试")
    parser.add_argument(
        "--replay-speed",
        type=float,
        default=1.0,
        help="开发回放倍速；默认 1× 实时",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="自动完成本机 MVP 回放验证并导出工件",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="--verify 的工件输出目录",
    )
    arguments = parser.parse_args(argv)
    if arguments.replay_speed <= 0:
        parser.error("--replay-speed 必须大于 0")
    if arguments.verify and arguments.output_dir is None:
        parser.error("--verify 必须提供 --output-dir")
    if arguments.output_dir is not None and not arguments.verify:
        parser.error("--output-dir 仅可与 --verify 一起使用")
    return arguments


def arm_fixture_position_guidance(
    controller: ApplicationController,
    *,
    replay_speed: float,
    schedule=QTimer.singleShot,
) -> None:
    """Simulate the fixture's stable contact gate before every replay stage."""

    controller.on_position_observation(
        now_seconds=0,
        contact_ready=True,
        in_valid_area=True,
    )
    schedule(
        max(1, round(3000 / replay_speed)),
        lambda: controller.on_position_observation(
            now_seconds=3,
            contact_ready=True,
            in_valid_area=True,
        ),
    )


def build_local_replay_runtime(
    *,
    replay_speed: float,
    storage_root: Path | None = None,
    export_destination: Path | None = None,
) -> LocalReplayRuntime:
    """Build the local-only replay UI once for manual and automated use."""

    fixture_bootstrap = FixtureReplayBootstrap(FixtureReplaySource.from_repository)
    source = fixture_bootstrap.source or UnavailableFixtureReplaySource()
    hardware = active_hardware_runtime()
    standardizer = (
        hardware.make_live_standardizer(
            replay_debug_profile(fixture_sha256=source.fixture_sha256)
        )
        if fixture_bootstrap.source is not None
        else None
    )
    raw, display = hardware.make_latest_frame_mailbox(), LatestDisplayFrameMailbox()
    acquisition = FixtureReplayAcquisition(source, raw, speed=replay_speed)
    store = LocalReplayStore(storage_root)
    from client.workflow.participant import ParticipantWorkflow

    participant = ParticipantWorkflow(
        tenant_id="local-replay", issuer="local", subjects=store, audit=store
    )
    consent = ConsentWorkflow(
        tenant_id="local-replay",
        terminal_id="local-replay",
        consents=type(
            "Consents",
            (),
            {"find_valid": store.find_valid, "create": store.create_consent},
        )(),
    )
    replay_protocol = default_standard_protocol()
    runtime = build_connected_ui(
        preflight=fixture_bootstrap,
        sessions=store,
        acquisition=acquisition,
        processor=V1ReplayDebugProcessor(
            StandardizedReplaySource(source, standardizer) if standardizer else source,
            report_sink=store,
        ),
        delivery=ReportDeliveryService(BasicReportPdfRenderer()),
        persisted_reports=store,
        spooler=_Print(),
        telemetry=_Telemetry(),
        display_refresh=DisplayRefreshController(
            display,
            maximum_refresh_hz=hardware.display_geometry.maximum_refresh_hz,
        ),
        export_destination=lambda: export_destination
        or Path.cwd() / "replay-debug-report.pdf",
        protocol=ProtocolCatalog((replay_protocol,)).select(
            ProtocolParadigm.STANDARD_BILATERAL,
            FeatureFlags(
                enabled_protocol_ids=(replay_protocol.protocol_id,),
                allow_pilot_protocols_for_replay_debug=True,
            ),
        ),
        data_source_mode="REPLAY_DEBUG",
        controller_options={
            "participant": participant,
            "consent": consent,
            "consent_policy": ConsentPolicy(
                "local-replay/1", ("SCREENING",), ("REPLAY_DEBUG",)
            ),
            "live_display": LiveDisplayProjection(
                source=raw, destination=display, standardizer=standardizer
            )
            if standardizer
            else None,
            "read_models": store,
            "physical_grid": PhysicalGridOverlay.from_hardware_geometry(
                hardware.display_geometry, specification_id=hardware.specification_id
            ),
        },
    )
    return LocalReplayRuntime(source, acquisition, store, runtime.controller)


def run_local_mvp_validation(*, output_dir: Path, replay_speed: float):
    """Run the reusable local replay composition in automated verification mode."""

    from client.app.local_mvp_validation import run_local_mvp_validation as run_validation

    return run_validation(output_dir=output_dir, replay_speed=replay_speed)


def main(argv: list[str] | None = None) -> int:
    arguments = parse_replay_arguments(sys.argv[1:] if argv is None else argv)
    if arguments.verify:
        return run_local_mvp_validation(
            output_dir=arguments.output_dir,
            replay_speed=arguments.replay_speed,
        ).exit_code
    app = QApplication.instance() or QApplication(sys.argv)
    app.setWindowIcon(application_icon())
    runtime = build_local_replay_runtime(replay_speed=arguments.replay_speed)
    controller = runtime.controller
    acquisition = runtime.acquisition
    enter_position = controller.window.findChild(QPushButton, "ENTER_POSITION")
    enter_position.clicked.connect(
        lambda: QTimer.singleShot(
            0,
            lambda: arm_fixture_position_guidance(
                controller,
                replay_speed=arguments.replay_speed,
            ),
        )
    )

    def complete_replay_stage() -> None:
        controller.on_acquisition_elapsed(20)
        QTimer.singleShot(
            0,
            lambda: arm_fixture_position_guidance(
                controller,
                replay_speed=arguments.replay_speed,
            ),
        )

    acquisition.set_callbacks(
        on_progress=lambda seconds: controller.on_acquisition_elapsed(seconds),
        on_complete=complete_replay_stage,
    )
    controller.window.show()
    return app.exec()
