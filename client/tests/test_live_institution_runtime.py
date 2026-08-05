from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace

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

        def make_latest_frame_mailbox(self):
            return object()

    class Institution:
        @staticmethod
        def open(*_args, **_kwargs):
            return institution

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
    physical_store: PhysicalStore | None = None
    baseline: object | None = None
    acquisition: Acquisition | None = None
    capture: Capture | None = None
    processor: Processor | None = None

    def make_capture(**kwargs):
        nonlocal capture
        capture = Capture(**kwargs)
        return capture

    def make_physical_store(*args):
        nonlocal physical_store
        physical_store = PhysicalStore(*args)
        return physical_store

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
    monkeypatch.setattr(live_runtime, "KeyringAesKeyProvider", lambda: object())
    monkeypatch.setattr(live_runtime, "InstitutionLocalStore", Institution)
    monkeypatch.setattr(live_runtime, "StateStore", make_physical_store)
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
            tenant_id="tenant-1", client_installation_id="installation-1"
        ),
        access_runtime=SimpleNamespace(
            hardware_lease_lifecycle=lambda _session: object()
        ),
        startup_run=object(),
        data_root=tmp_path,
        export_destination=lambda: None,
    )

    assert (
        acquisition is not None
        and capture is not None
        and processor is not None
        and physical_store is not None
        and baseline is not None
    )
    assert len(inspect.signature(acquisition.capture_session).parameters) == 2
    assert events.index("processor") < events.index("callbacks")
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
