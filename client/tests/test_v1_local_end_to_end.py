from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtWidgets import QCheckBox, QLineEdit, QPushButton

from client.app.fixture_replay import FixtureReplayAcquisition, FixtureReplayBootstrap, FixtureReplaySource
from client.app.fixture_replay import StandardizedReplaySource
from client.app.live_display import LiveDisplayProjection
from client.app.local_entry import _Print, _Telemetry
from client.app.local_store import LocalReplayStore
from client.app.pages import PageId
from client.app.ui_integration import build_connected_ui
from client.device.acquisition import LatestFrameMailbox
from client.local_analysis.display import DisplayRefreshController, LatestDisplayFrameMailbox
from client.local_analysis.v1_debug import V1ReplayDebugProcessor
from client.reporting.delivery import ReportDeliveryService
from client.reporting.pdf import BasicReportPdfRenderer
from client.security.key_envelope import DualEnvelopeBlobCodec, KeyringTerminalKeyHandle, ServerKeyset, generate_test_keypair
from client.hardware_standardization.live_processing import DoP4864LiveFrameStandardizer, replay_debug_profile
from client.hardware_standardization.do_p4864 import DoP4864StandardizationAdapter
from client.workflow.consent import ConsentPolicy, ConsentWorkflow
from client.workflow.participant import ParticipantWorkflow
from client.workflow.state_machine import ScreeningStep


class _MemoryKeyring:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, account: str) -> str | None:
        return self.values.get((service, account))

    def set_password(self, service: str, account: str, value: str) -> None:
        self.values[(service, account)] = value


def test_local_v1_replay_runs_from_subject_entry_to_persisted_pdf_and_history(qtbot, tmp_path: Path) -> None:
    replay_speed = float(os.environ.get("FEETFORCEPLATE_REPLAY_SPEED", "500"))
    source = FixtureReplaySource.from_repository()
    standardizer = DoP4864LiveFrameStandardizer(
        replay_debug_profile(fixture_sha256=source.fixture_sha256)
    )
    server = generate_test_keypair()
    store = LocalReplayStore(
        tmp_path,
        codec=DualEnvelopeBlobCodec(
            server_keyset=ServerKeyset("replay-dev-no-cloud", server.public_key_pem),
            terminal_key=KeyringTerminalKeyHandle(
                service_name="FeetForcePlate.test",
                account_name="terminal-e2e",
                keyring_backend=_MemoryKeyring(),
            ),
        ),
    )
    raw, display = LatestFrameMailbox(), LatestDisplayFrameMailbox()
    acquisition = FixtureReplayAcquisition(source, raw, speed=replay_speed)
    participant = ParticipantWorkflow(
        tenant_id="local-replay", issuer="local", subjects=store, audit=store
    )
    consent = ConsentWorkflow(
        tenant_id="local-replay",
        terminal_id="local-replay",
        consents=type("Consents", (), {"find_valid": store.find_valid, "create": store.create_consent})(),
    )
    pdf_path = tmp_path / "report.pdf"
    runtime = build_connected_ui(
        preflight=FixtureReplayBootstrap(lambda: source),
        sessions=store,
        acquisition=acquisition,
        processor=V1ReplayDebugProcessor(StandardizedReplaySource(source, standardizer), report_sink=store),
        delivery=ReportDeliveryService(BasicReportPdfRenderer()),
        persisted_reports=store,
        spooler=_Print(),
        telemetry=_Telemetry(),
        display_refresh=DisplayRefreshController(
            display,
            maximum_refresh_hz=(
                DoP4864StandardizationAdapter.observed_compact_8bit()
                .specification.observed_frame_rate_hz
            ),
        ),
        export_destination=lambda: pdf_path,
        data_source_mode="REPLAY_DEBUG",
        controller_options={
            "participant": participant,
            "consent": consent,
            "consent_policy": ConsentPolicy("local-replay/1", ("SCREENING",), ("REPLAY_DEBUG",)),
            "live_display": LiveDisplayProjection(
                source=raw, destination=display, standardizer=standardizer
            ),
            "read_models": store,
        },
    )
    controller = runtime.controller
    qtbot.addWidget(controller.window)

    def complete_stage() -> None:
        controller.on_acquisition_elapsed(20)

    acquisition.set_callbacks(
        on_progress=lambda seconds: controller.on_acquisition_elapsed(seconds),
        on_complete=complete_stage,
    )
    controller.dispatch("START_NEW_SCREENING")
    controller.window.findChild(QLineEdit, "subjectExternalIdInput").setText("DEMO-0001")
    controller.dispatch("LOOKUP_SUBJECT")
    controller.dispatch("CONFIRM_SUBJECT")
    controller.dispatch("SKIP_PROFILE")
    controller.window.findChild(QCheckBox, "requiredConsent").setChecked(True)
    controller.dispatch("CONFIRM_CONSENT")

    qtbot.waitUntil(
        lambda: controller._coordinator.state.step is ScreeningStep.PREFLIGHT
        and controller._coordinator.state.preflight_ready,
        timeout=5_000,
    )
    assert {check.key for check in controller._coordinator.state.preflight_checks} == {
        "device_connected",
        "storage_space",
        "calibration_status",
        "data_sync",
        "zero_load",
    }
    controller.dispatch("ENTER_POSITION")

    for stage_index in range(4):
        qtbot.waitUntil(
            lambda: controller._coordinator.state.step
            is ScreeningStep.POSITION_GUIDANCE,
            timeout=5_000,
        )
        controller.on_position_observation(
            now_seconds=float(stage_index * 10),
            contact_ready=True,
            in_valid_area=True,
        )
        controller.on_position_observation(
            now_seconds=float(stage_index * 10 + 3),
            contact_ready=True,
            in_valid_area=True,
        )
        assert controller._coordinator.state.step is ScreeningStep.POSITION_GUIDANCE
        assert controller._coordinator.state.position_guidance.manual_start_allowed
        controller.dispatch("START_ACQUISITION")
        expected_step = (
            ScreeningStep.POSITION_GUIDANCE
            if stage_index < 3
            else ScreeningStep.BASIC_REPORT
        )
        qtbot.waitUntil(
            lambda expected=expected_step: controller._coordinator.state.step
            is expected,
            timeout=int(5_000 + 25_000 / replay_speed),
        )

    state = controller._coordinator.state
    assert state.report_id is not None and state.report_version is not None
    assert store.db.execute("SELECT COUNT(*) FROM replay_stage_completions").fetchone()[0] == 4
    controller.dispatch("VIEW_BASIC_REPORT")
    controller.dispatch("EXPORT_PDF")
    assert pdf_path.exists() and pdf_path.stat().st_size > 0
    assert store.db.execute(
        "SELECT event_type FROM subject_audit_events ORDER BY rowid"
    ).fetchall() == [("SUBJECT_EXPORT",)]
    controller.window.present_records(store.recent_records())
    controller.window.page_widget(PageId.RECORDS).findChild(QPushButton, "recordsTableView0").click()
    assert controller.window.current_page_id is PageId.REPORT_PREVIEW
