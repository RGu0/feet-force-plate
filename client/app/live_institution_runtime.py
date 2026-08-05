"""Composition root for the authenticated, real-hardware institution UI."""

from __future__ import annotations

from pathlib import Path
import time

from client.app.heatmap import PhysicalGridOverlay
from client.app.institution_store import InstitutionLocalStore, KeyringAesKeyProvider
from client.app.live_baseline import LiveBaselinePreflight
from client.app.live_display import LiveDisplayProjection
from client.app.live_hardware_acquisition import QtLiveHardwareAcquisition
from client.app.live_physical_workflow import (
    InstitutionLiveSessions,
    LivePhysicalCapture,
    LivePhysicalProcessor,
)
from client.app.preflight import HardwareLeasePreflight, build_production_preflight
from client.app.ui_integration import build_connected_ui
from client.cloud.runtime import AuthenticatedInstitutionSession, ClientAccessRuntime
from client.hardware_standardization.live_processing import DoP4864LiveProcessingProfile
from client.hardware_standardization.runtime import active_hardware_runtime
from client.local_analysis.display import DisplayRefreshController, LatestDisplayFrameMailbox
from client.reporting.delivery import ReportDeliveryService
from client.reporting.pdf import BasicReportPdfRenderer
from client.spool.state_store import SensitiveBlobCodec, StateStore
from client.workflow.consent import ConsentPolicy, ConsentWorkflow
from client.workflow.participant import ParticipantWorkflow
from client.workflow.protocol import default_standard_protocol


class _Telemetry:
    def record_error(self, **_event) -> None:
        pass


class _Print:
    def print_pdf(self, _pdf_path, *, job_name):
        _ = job_name


class _DeferredBaselineStandardizer:
    """The P-07 display can start only after P-05 produced this session's reference."""

    def __init__(self, hardware, baseline: LiveBaselinePreflight) -> None:
        self._hardware = hardware
        self._baseline = baseline

    def standardize(self, frame):
        reference = self._baseline.reference
        if reference is None:
            raise RuntimeError("live display requires the P-05 empty-board baseline")
        return self._hardware.make_live_standardizer(
            DoP4864LiveProcessingProfile(
                version="do-p4864/institution-live-display/1",
                baseline_reference=reference,
            )
        ).standardize(frame)


def build_live_institution_runtime(
    *,
    session: AuthenticatedInstitutionSession,
    access_runtime: ClientAccessRuntime,
    startup_run,
    data_root: Path,
    export_destination,
):
    """Build the P-01–P-10 UI after P-00 authentication and startup pass."""

    hardware = active_hardware_runtime()
    key_provider = KeyringAesKeyProvider()
    institution = InstitutionLocalStore.open(
        data_root / "institution", key_provider=key_provider
    )
    physical_store = StateStore(
        data_root / "database" / "institution-live.sqlite3",
        SensitiveBlobCodec(key_provider),
    )
    physical_store.record_successful_online(time.time_ns())
    sessions = InstitutionLiveSessions(institution)
    baseline = LiveBaselinePreflight(hardware)
    lease = HardwareLeasePreflight(access_runtime.hardware_lease_lifecycle(session))
    preflight = build_production_preflight(
        startup_run=startup_run,
        new_test_gate=physical_store,
        storage_root=data_root,
        hardware=hardware,
        hardware_lease=lease,
        live_baseline=baseline,
    )
    raw_mailbox = hardware.make_latest_frame_mailbox()
    display_mailbox = LatestDisplayFrameMailbox()
    capture = LivePhysicalCapture(
        hardware=hardware,
        sessions=sessions,
        baseline=baseline,
        physical_store=physical_store,
        key_provider=key_provider,
        spool_root=data_root / "spool",
        latest_frames=raw_mailbox,
    )
    acquisition = QtLiveHardwareAcquisition(capture.capture)
    processor = LivePhysicalProcessor(
        sessions=sessions,
        physical_store=physical_store,
        key_provider=key_provider,
        spool_root=data_root / "spool",
        reports=institution,
    )
    participant = ParticipantWorkflow(
        tenant_id=session.tenant_id,
        issuer="institution-ui",
        subjects=institution,
        audit=institution,
    )
    consent = ConsentWorkflow(
        tenant_id=session.tenant_id,
        terminal_id=session.client_installation_id,
        consents=institution.consent_port(),
    )
    runtime = build_connected_ui(
        preflight=preflight,
        sessions=sessions,
        acquisition=acquisition,
        processor=processor,
        delivery=ReportDeliveryService(BasicReportPdfRenderer()),
        spooler=_Print(),
        telemetry=_Telemetry(),
        display_refresh=DisplayRefreshController(
            display_mailbox,
            maximum_refresh_hz=hardware.display_geometry.maximum_refresh_hz,
        ),
        live_display=LiveDisplayProjection(
            source=raw_mailbox,
            destination=display_mailbox,
            standardizer=_DeferredBaselineStandardizer(hardware, baseline),
        ),
        export_destination=export_destination,
        protocol=default_standard_protocol(),
        persisted_reports=institution,
        data_source_mode="LIVE",
        controller_options={
            "participant": participant,
            "consent": consent,
            "consent_policy": ConsentPolicy("institution-screening/1", ("SCREENING",), ("SCREENING",)),
            "physical_grid": PhysicalGridOverlay.from_hardware_geometry(
                hardware.display_geometry, specification_id=hardware.specification_id
            ),
        },
    )
    acquisition.set_callbacks(
        on_progress=runtime.controller.on_acquisition_elapsed,
        on_complete=lambda result: runtime.controller.on_live_hardware_capture_completed(
            result, record_attestations=processor.record_attestations
        ),
        on_failure=runtime.controller.on_live_hardware_capture_failed,
    )
    # Keep owned resources reachable for the lifetime of the visible workbench.
    runtime.controller.window.setProperty(
        "institutionLiveResources",
        (institution, physical_store, acquisition, capture, baseline),
    )
    return runtime
