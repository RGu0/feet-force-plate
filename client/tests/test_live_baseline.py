from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from client.hardware_integration.live_baseline import LiveBaselinePreflight
from client.hardware_standardization.runtime import active_hardware_runtime


class _Transport:
    def __init__(self) -> None:
        self.closed = False

    def read(self, _size: int) -> bytes:
        return b"frame"

    def close(self) -> None:
        self.closed = True


class _Parser:
    def __init__(self, values: np.ndarray) -> None:
        self.index = 0
        self.values = values

    def feed(self, _chunk: bytes):
        value = active_hardware_runtime().make_fixture_frame(
            self.values, source_index=self.index,
            host_monotonic_ns=self.index * 1_000_000_000, quality_flags=frozenset(),
        )
        self.index += 1
        return (value,)


class _Hardware:
    def __init__(self, values: np.ndarray | None = None) -> None:
        self.baseline_configuration = active_hardware_runtime().baseline_configuration
        self.transport = _Transport()
        self.values = values if values is not None else np.zeros((48, 64), dtype=np.uint8)

    def connect_startup(self):
        return SimpleNamespace(transport=self.transport, parser=_Parser(self.values))


def test_preflight_collects_a_fresh_encrypted_session_baseline_before_position_guidance() -> None:
    preflight = LiveBaselinePreflight(_Hardware(), monotonic_ns=lambda: 1)

    check = preflight.acquire_for_new_session()

    assert check.ready
    assert check.key == "live_baseline"
    assert preflight.reference is not None


def test_preflight_accepts_an_unloaded_board_with_one_persistent_sensor_offset() -> None:
    values = np.zeros((48, 64), dtype=np.uint8)
    values[0, 0] = 5
    preflight = LiveBaselinePreflight(_Hardware(values), monotonic_ns=lambda: 1)

    check = preflight.acquire_for_new_session()

    assert check.ready
    assert preflight.reference is not None
    assert preflight.reference.zero_offset_count[0] == 5.0
