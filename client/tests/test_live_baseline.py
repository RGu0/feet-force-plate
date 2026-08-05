from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from client.app.live_baseline import LiveBaselinePreflight
from client.hardware_standardization.runtime import active_hardware_runtime


class _Transport:
    def __init__(self) -> None:
        self.closed = False

    def read(self, _size: int) -> bytes:
        return b"frame"

    def close(self) -> None:
        self.closed = True


class _Parser:
    def __init__(self) -> None:
        self.index = 0

    def feed(self, _chunk: bytes):
        value = active_hardware_runtime().make_fixture_frame(
            np.zeros((48, 64), dtype=np.uint8), source_index=self.index,
            host_monotonic_ns=self.index * 1_000_000_000, quality_flags=frozenset(),
        )
        self.index += 1
        return (value,)


class _Hardware:
    def __init__(self) -> None:
        self.baseline_configuration = active_hardware_runtime().baseline_configuration
        self.transport = _Transport()

    def connect_startup(self):
        return SimpleNamespace(transport=self.transport, parser=_Parser())


def test_preflight_collects_a_fresh_encrypted_session_baseline_before_position_guidance() -> None:
    preflight = LiveBaselinePreflight(_Hardware(), monotonic_ns=lambda: 1)

    check = preflight.acquire_for_new_session()

    assert check.ready
    assert check.key == "live_baseline"
    assert preflight.reference is not None
