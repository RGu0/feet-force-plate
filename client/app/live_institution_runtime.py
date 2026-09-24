"""Composition root for the authenticated, real-hardware institution UI."""

from __future__ import annotations

from pathlib import Path

from client.app.heatmap import PhysicalGridOverlay
from client.app.institution_read_models import InstitutionUiReadModels
from client.app.report_index_recovery import recover_missing_screening_records
from client.hardware_integration.live_baseline import LiveBaselinePreflight
from client.app.live_display import LiveDisplayProjection
from client.hardware_integration.live_hardware_acquisition import QtLiveHardwareAcquisition
from client.hardware_integration.live_physical_workflow import (
    FormalCaptureUpload,
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
from client.support import SafeClientEventName, SafeClientEventOutcome
from client.workflow.consent import ConsentPolicy, ConsentWorkflow
from client.workflow.participant import ParticipantWorkflow
from client.workflow.protocol import default_standard_protocol


class _Telemetry:
    """Record only allow-listed live-capture failure metadata."""

    _LIVE_CAPTURE_CODES = frozenset({"E-ACQ-001", "E-ACQ-004", "E-DEV-002"})

    def __init__(self, recorder=None) -> None:
        self._recorder = recorder

    def record_error(self, *, code: str, **_event) -> None:
        if self._recorder is None:
            return
        if code == "E-RPT-001":
            self._recorder.record(
                SafeClientEventName.REPORT_GENERATION_FAILED,
                SafeClientEventOutcome.FAILED,
                error_code=code,
            )
            return
        if code not in self._LIVE_CAPTURE_CODES:
            return
        technical_detail = str(_event.get("technical_detail", ""))
        event_name = SafeClientEventName.LIVE_CAPTURE_FAILED
        if code == "E-ACQ-004":
            if "capture connection failed:" in technical_detail:
                event_name = SafeClientEventName.LIVE_CAPTURE_CONNECTION_FAILED
            elif "capture initialization failed: metadata" in technical_detail:
                event_name = SafeClientEventName.LIVE_CAPTURE_METADATA_FAILED
            elif "capture initialization failed: local-identity" in technical_detail:
                event_name = SafeClientEventName.LIVE_CAPTURE_LOCAL_IDENTITY_FAILED
            elif "capture initialization failed: formal-envelope/missing-local-record" in technical_detail:
                event_name = SafeClientEventName.LIVE_CAPTURE_FORMAL_ENVELOPE_LOCAL_RECORD_MISSING
            elif "capture initialization failed: formal-envelope/invalid-contract-value" in technical_detail:
                event_name = SafeClientEventName.LIVE_CAPTURE_FORMAL_ENVELOPE_CONTRACT_VALUE_INVALID
            elif "capture initialization failed: formal-envelope/invalid-contract-type" in technical_detail:
                event_name = SafeClientEventName.LIVE_CAPTURE_FORMAL_ENVELOPE_CONTRACT_TYPE_INVALID
            elif "capture initialization failed: formal-envelope/unexpected" in technical_detail:
                event_name = SafeClientEventName.LIVE_CAPTURE_FORMAL_ENVELOPE_UNEXPECTED
            elif "capture initialization failed: formal-envelope" in technical_detail:
                event_name = SafeClientEventName.LIVE_CAPTURE_FORMAL_ENVELOPE_FAILED
            elif "capture initialization failed: session-stager" in technical_detail:
                event_name = SafeClientEventName.LIVE_CAPTURE_SESSION_STAGER_FAILED
            elif "capture initialization failed:" in technical_detail:
                event_name = SafeClientEventName.LIVE_CAPTURE_INITIALIZATION_FAILED
            elif "transport disconnected:" in technical_detail:
                event_name = SafeClientEventName.LIVE_CAPTURE_TRANSPORT_DISCONNECTED
            elif "no valid decoded signal" in technical_detail:
                event_name = SafeClientEventName.LIVE_CAPTURE_SIGNAL_TIMEOUT
            elif "stage capture failed at DECODE:" in technical_detail:
                event_name = SafeClientEventName.LIVE_CAPTURE_DECODE_FAILED
            elif "stage capture failed at GATE:" in technical_detail:
                event_name = SafeClientEventName.LIVE_CAPTURE_GATE_FAILED
            elif "stage capture failed at DISPLAY:" in technical_detail:
                event_name = SafeClientEventName.LIVE_CAPTURE_DISPLAY_HANDOFF_FAILED
            elif (
                "storage handoff failed:" in technical_detail
                or "stage capture failed at STAGE_" in technical_detail
            ):
                event_name = SafeClientEventName.LIVE_CAPTURE_STAGE_STORAGE_FAILED
            elif technical_detail.startswith("RetryableStageCaptureError:"):
                event_name = SafeClientEventName.LIVE_CAPTURE_STREAM_FAILED
        self._recorder.record(
            event_name,
            SafeClientEventOutcome.FAILED,
            error_code=code,
        )


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
    key_provider,
    institution,
    physical_store,
    startup_run,
    data_root: Path,
    export_destination,
    app_version: str,
    payload_schema: str,
    event_recorder=None,
):
    """Build the P-01–P-10 UI after P-00 authentication and startup pass."""

    hardware = active_hardware_runtime()
    client_installation_id = getattr(session, "client_installation_id", None)
    if not isinstance(client_installation_id, str) or not client_installation_id.strip():
        raise ValueError("client_installation_id is required for formal runtime")
    hardware_asset_id = getattr(session, "hardware_asset_id", None)
    if not isinstance(hardware_asset_id, str) or not hardware_asset_id.strip():
        raise ValueError("hardware_asset_id is required for formal runtime")
    calibration = hardware.calibration_metadata
    formal_upload = FormalCaptureUpload(
        client_installation_id=client_installation_id,
        hardware_asset_id=hardware_asset_id,
        site_id=getattr(session, "site_id", None),
        app_version=app_version,
        payload_schema=payload_schema,
        calibration_profile=calibration.profile_version,
    )
    sessions = InstitutionLiveSessions(
        institution, tenant_id=session.tenant_id,
        installation_id=client_installation_id,
        replenish=lambda: access_runtime.replenish_capture_grants(institution, session),
    )
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
        formal_upload=formal_upload,
    )
    acquisition = QtLiveHardwareAcquisition(
        capture.capture,
        prepare_session=capture.prepare_session,
    )
    processor = LivePhysicalProcessor(
        sessions=sessions,
        physical_store=physical_store,
        key_provider=key_provider,
        spool_root=data_root / "spool",
        reports=institution,
    )
    recover_missing_screening_records(
        institution=institution,
        physical_store=physical_store,
        tenant_id=session.tenant_id,
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
        telemetry=_Telemetry(event_recorder),
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
            "read_models": InstitutionUiReadModels(
                institution=institution,
                tenant_id=session.tenant_id,
                physical_store=physical_store,
                app_version=app_version,
            ),
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
