from __future__ import annotations

from collections.abc import Callable

import numpy as np

from client.device.protocol import DaoOneP4864Parser, ProtocolProfile
from client.device.simulator import (
    FaultKind,
    FaultPlan,
    SyntheticP4864Transport,
)
from client.startup_validation.models import ValidationOutcome, ValidationReason
from client.startup_validation.service import (
    CollectionPhase,
    DeviceValidationService,
    ValidationRequest,
)


def _profile() -> ProtocolProfile:
    return ProtocolProfile.synthetic(
        version="do-p4864/startup-validation-test-1",
        length_byte_order="little",
        checksum_start=0,
        checksum_end=3077,
    )


def _empty_frame(index: int) -> np.ndarray:
    rows, columns = np.indices((48, 64))
    return ((rows + columns + index) % 3).astype(np.uint8)


def _request(*, previous: str | None = None, attempt: int = 1) -> ValidationRequest:
    return ValidationRequest(
        terminal_id="terminal-opaque-test",
        device_ref="port-hash-test",
        app_version="0.1.0-test",
        previous_validation_run_id=previous,
        attempt_number=attempt,
    )


def _service(
    *,
    frame_source: Callable[[int], np.ndarray] = _empty_frame,
    timestamps: list[int] | None = None,
    fault_plan: FaultPlan | None = None,
    max_frames: int = 140,
) -> DeviceValidationService:
    frame_times = iter(
        timestamps
        or [index * 50_000_000 for index in range(max_frames + 10)]
    )
    parser = DaoOneP4864Parser(
        _profile(),
        allow_unverified=True,
        monotonic_ns=lambda: next(frame_times),
        wall_time_ns=lambda: 1_800_000_000_000_000_000,
    )
    transport = SyntheticP4864Transport(
        _profile(),
        realtime=False,
        max_frames=max_frames,
        frame_source=frame_source,
        fault_plan=fault_plan,
    )
    return DeviceValidationService(
        transport=transport,
        parser=parser,
        wall_time_ns=lambda: 1_800_000_006_000_000_000,
        id_factory=lambda: "validation-run-fixed",
        diagnostic_id_factory=lambda: "diagnostic-fixed",
    )


def test_window_starts_on_first_valid_unloaded_frame_and_spans_full_five_seconds() -> None:
    progress = []

    run = _service().run(_request(), on_progress=progress.append)

    assert run.outcome is ValidationOutcome.PASS
    assert run.statistics is not None
    assert run.statistics.duration_ns >= 5_000_000_000
    assert run.statistics.valid_frame_count == 101
    assert run.statistics.valid_frame_count != round(5 * 20.7)
    assert progress[0].phase is CollectionPhase.WAITING_FOR_EMPTY
    collecting = [item for item in progress if item.phase is CollectionPhase.COLLECTING_BASELINE]
    assert collecting[0].elapsed_ns == 0
    assert collecting[-1].elapsed_ns >= 5_000_000_000
    assert all(left.fraction <= right.fraction for left, right in zip(collecting, collecting[1:]))
    assert progress[-1].phase is CollectionPhase.VALIDATING


def test_obvious_load_discards_the_partial_window() -> None:
    run = _service(
        frame_source=lambda _index: np.full((48, 64), 30, dtype=np.uint8)
    ).run(_request())

    assert run.outcome is ValidationOutcome.RETRYABLE_FAIL
    assert run.reason is ValidationReason.LOAD_NOT_EMPTY
    assert run.partial_window_discarded
    assert run.statistics is not None
    assert run.statistics.valid_frame_count == 1


def test_disconnect_discards_the_partial_window() -> None:
    run = _service(
        fault_plan=FaultPlan(events={40: (FaultKind.DISCONNECT,)})
    ).run(_request())

    assert run.outcome is ValidationOutcome.RETRYABLE_FAIL
    assert run.reason is ValidationReason.STREAM_INTERRUPTED
    assert run.partial_window_discarded
    assert run.statistics is not None
    assert 0 < run.statistics.duration_ns < 5_000_000_000


def test_empty_reads_after_collection_starts_are_a_stream_interruption() -> None:
    class EmptyAfterOneTransport:
        def __init__(self) -> None:
            encoded_transport = SyntheticP4864Transport(
                _profile(),
                realtime=False,
                max_frames=1,
                frame_source=_empty_frame,
            )
            self.first = encoded_transport.read(3079)
            self.reads = 0

        def read(self, _max_bytes: int) -> bytes:
            self.reads += 1
            return self.first if self.reads == 1 else b""

        def close(self) -> None:
            pass

    host_now = iter([0, 100_000_000, 200_000_000, 300_000_001])
    parser = DaoOneP4864Parser(
        _profile(),
        allow_unverified=True,
        monotonic_ns=lambda: 0,
        wall_time_ns=lambda: 1,
    )
    service = DeviceValidationService(
        transport=EmptyAfterOneTransport(),
        parser=parser,
        monotonic_ns=lambda: next(host_now),
        wall_time_ns=lambda: 2,
        id_factory=lambda: "run-stall",
        diagnostic_id_factory=lambda: "diag-stall",
    )

    run = service.run(_request())

    assert run.reason is ValidationReason.STREAM_INTERRUPTED
    assert run.partial_window_discarded


def test_retry_uses_a_new_run_id_and_does_not_reuse_old_window() -> None:
    ids = iter(["run-first", "run-second"])
    first_service = _service(
        fault_plan=FaultPlan(events={10: (FaultKind.DISCONNECT,)})
    )
    first_service._id_factory = lambda: next(ids)
    first = first_service.run(_request())
    second_service = _service()
    second_service._id_factory = lambda: next(ids)

    second = second_service.run(
        _request(previous=first.validation_run_id, attempt=2)
    )

    assert first.validation_run_id == "run-first"
    assert second.validation_run_id == "run-second"
    assert second.previous_validation_run_id == first.validation_run_id
    assert second.statistics is not None
    assert second.statistics.start_source_index == 0
    assert second.statistics.valid_frame_count == 101
