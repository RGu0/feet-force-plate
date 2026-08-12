from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest

from client.app import live_institution_runtime as live_runtime


class _FakeWindow:
    def __init__(self) -> None:
        self.properties: dict[str, object] = {}

    def setProperty(self, name: str, value: object) -> None:
        self.properties[name] = value


class _FakeController:
    def __init__(self) -> None:
        self.window = _FakeWindow()
        self.progress: list[int] = []
        self.completions: list[tuple[object, object]] = []
        self.failures: list[str] = []

    def on_acquisition_elapsed(self, elapsed_seconds: int) -> None:
        self.progress.append(elapsed_seconds)

    def on_live_hardware_capture_completed(
        self, result: object, *, record_attestations: object
    ) -> None:
        self.completions.append((result, record_attestations))

    def on_live_hardware_capture_failed(self, detail: str) -> None:
        self.failures.append(detail)


def test_live_runtime_owns_staged_capture_and_forwards_worker_callbacks(
    monkeypatch, tmp_path: Path
) -> None:
    events: list[str] = []

    class Hardware:
        display_geometry = SimpleNamespace(maximum_refresh_hz=20)
        specification_id = "dop4864/test"
        calibration_metadata = SimpleNamespace(
            profile_version="calibration-authoritative/42"
        )

        def make_latest_frame_mailbox(self):
            return object()

    class PhysicalStore:
        def __init__(self, *_args) -> None:
            pass

        def record_successful_online(self, _timestamp_ns: int) -> None:
            pass

    class Capture:
        def __init__(self, **_kwargs) -> None:
            events.append("capture")

        def capture(self, session_id: str, gate: object) -> object:
            return SimpleNamespace(session_id=session_id, gate=gate)

    class Acquisition:
        def __init__(self, capture_session) -> None:
            self.capture_session = capture_session
            self.callbacks: dict[str, object] = {}

        def set_callbacks(self, **callbacks) -> None:
            events.append("callbacks")
            self.callbacks = callbacks

    class Processor:
        def __init__(self, **_kwargs) -> None:
            events.append("processor")

        def record_attestations(self, *_args, **_kwargs) -> None:
            pass

    institution = SimpleNamespace(consent_port=lambda: object())
    controller = _FakeController()
    physical_store = PhysicalStore()
    baseline: object | None = None
    acquisition: Acquisition | None = None
    capture: Capture | None = None
    processor: Processor | None = None
    capture_kwargs: dict[str, object] = {}

    def make_capture(**kwargs):
        nonlocal capture
        capture_kwargs.update(kwargs)
        capture = Capture(**kwargs)
        return capture

    def make_baseline(_hardware):
        nonlocal baseline
        baseline = object()
        return baseline

    def make_acquisition(capture_session):
        nonlocal acquisition
        acquisition = Acquisition(capture_session)
        return acquisition

    def make_processor(**kwargs):
        nonlocal processor
        processor = Processor(**kwargs)
        return processor

    monkeypatch.setattr(live_runtime, "active_hardware_runtime", lambda: Hardware())
    monkeypatch.setattr(
        live_runtime,
        "KeyringAesKeyProvider",
        lambda: (_ for _ in ()).throw(AssertionError("workbench must reuse key provider")),
        raising=False,
    )
    monkeypatch.setattr(
        live_runtime,
        "InstitutionLocalStore",
        SimpleNamespace(
            open=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("workbench must reuse institution store")
            )
        ),
        raising=False,
    )
    monkeypatch.setattr(
        live_runtime,
        "StateStore",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("workbench must reuse physical store")
        ),
        raising=False,
    )
    monkeypatch.setattr(live_runtime, "InstitutionLiveSessions", lambda _store: object())
    monkeypatch.setattr(live_runtime, "LiveBaselinePreflight", make_baseline)
    monkeypatch.setattr(live_runtime, "HardwareLeasePreflight", lambda _lease: object())
    monkeypatch.setattr(live_runtime, "build_production_preflight", lambda **_kwargs: object())
    monkeypatch.setattr(live_runtime, "LatestDisplayFrameMailbox", lambda: object())
    monkeypatch.setattr(live_runtime, "LivePhysicalCapture", make_capture)
    monkeypatch.setattr(live_runtime, "QtLiveHardwareAcquisition", make_acquisition)
    monkeypatch.setattr(live_runtime, "LivePhysicalProcessor", make_processor)
    monkeypatch.setattr(live_runtime, "ParticipantWorkflow", lambda **_kwargs: object())
    monkeypatch.setattr(live_runtime, "ConsentWorkflow", lambda **_kwargs: object())
    monkeypatch.setattr(
        live_runtime,
        "PhysicalGridOverlay",
        SimpleNamespace(from_hardware_geometry=lambda *_args, **_kwargs: object()),
    )
    monkeypatch.setattr(live_runtime, "DisplayRefreshController", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(live_runtime, "LiveDisplayProjection", lambda **_kwargs: object())
    monkeypatch.setattr(live_runtime, "ReportDeliveryService", lambda *_args: object())
    monkeypatch.setattr(live_runtime, "BasicReportPdfRenderer", lambda: object())
    monkeypatch.setattr(live_runtime, "ConsentPolicy", lambda *_args: object())
    monkeypatch.setattr(
        live_runtime,
        "build_connected_ui",
        lambda **_kwargs: SimpleNamespace(controller=controller),
    )

    live_runtime.build_live_institution_runtime(
        session=SimpleNamespace(
            tenant_id="tenant-1",
            client_installation_id="c03732ad-c781-4364-9d3a-c3ce3ea8488c",
            hardware_asset_id="7d9238d9-0ef8-4de4-b0c5-f08e22b72268",
        ),
        access_runtime=SimpleNamespace(
            hardware_lease_lifecycle=lambda _session: object()
        ),
        key_provider=object(),
        institution=institution,
        physical_store=physical_store,
        startup_run=object(),
        data_root=tmp_path,
        export_destination=lambda: None,
        app_version="9.8.7-authoritative",
        payload_schema="raw-segment/7",
    )

    assert (
        acquisition is not None
        and capture is not None
        and processor is not None
        and baseline is not None
    )
    assert len(inspect.signature(acquisition.capture_session).parameters) == 2
    assert events.index("processor") < events.index("callbacks")
    formal_upload = capture_kwargs["formal_upload"]
    assert formal_upload.client_installation_id == (
        "c03732ad-c781-4364-9d3a-c3ce3ea8488c"
    )
    assert formal_upload.hardware_asset_id == "7d9238d9-0ef8-4de4-b0c5-f08e22b72268"
    assert formal_upload.app_version == "9.8.7-authoritative"
    assert formal_upload.payload_schema == "raw-segment/7"
    assert formal_upload.calibration_profile == "calibration-authoritative/42"
    callbacks = acquisition.callbacks
    callbacks["on_progress"](7)
    result = SimpleNamespace(stage_windows=("window-1",))
    callbacks["on_complete"](result)
    callbacks["on_failure"]("stage failure")
    assert controller.progress == [7]
    assert controller.completions == [(result, processor.record_attestations)]
    assert controller.failures == ["stage failure"]
    assert controller.window.properties["institutionLiveResources"] == (
        institution,
        physical_store,
        acquisition,
        capture,
        baseline,
    )


def test_formal_live_runtime_rejects_missing_authenticated_hardware_asset(
    monkeypatch, tmp_path: Path
) -> None:
    hardware = SimpleNamespace(
        calibration_metadata=SimpleNamespace(profile_version="calibration/1")
    )
    monkeypatch.setattr(live_runtime, "active_hardware_runtime", lambda: hardware)
    monkeypatch.setattr(
        live_runtime,
        "KeyringAesKeyProvider",
        lambda: (_ for _ in ()).throw(
            AssertionError("storage must not open before formal identity validation")
        ),
        raising=False,
    )

    with pytest.raises(ValueError, match="hardware_asset_id"):
        live_runtime.build_live_institution_runtime(
            session=SimpleNamespace(
                tenant_id="tenant-1",
                client_installation_id="c03732ad-c781-4364-9d3a-c3ce3ea8488c",
            ),
            access_runtime=object(),
            key_provider=object(),
            institution=object(),
            physical_store=object(),
            startup_run=object(),
            data_root=tmp_path,
            export_destination=lambda: None,
            app_version="9.8.7-authoritative",
            payload_schema="raw-segment/7",
        )


def test_formal_live_runtime_requires_explicit_capture_versions(tmp_path: Path) -> None:
    with pytest.raises(TypeError, match="app_version"):
        live_runtime.build_live_institution_runtime(
            session=SimpleNamespace(
                tenant_id="tenant-1",
                client_installation_id="c03732ad-c781-4364-9d3a-c3ce3ea8488c",
                hardware_asset_id="7d9238d9-0ef8-4de4-b0c5-f08e22b72268",
            ),
            access_runtime=object(),
            key_provider=object(),
            institution=object(),
            physical_store=object(),
            startup_run=object(),
            data_root=tmp_path,
            export_destination=lambda: None,
        )
