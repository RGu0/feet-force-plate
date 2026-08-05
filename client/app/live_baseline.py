"""Collect a fresh unloaded baseline before the participant enters P-06."""

from __future__ import annotations

import hashlib
import time
from uuid import uuid4

import numpy as np

from client.device.transport import TransportDisconnected
from client.hardware_standardization.baseline import build_baseline_reference
from client.hardware_standardization.models import BaselineSample, UnloadedBaselineWindow
from client.workflow.models import PreflightCheck


class LiveBaselinePreflight:
    """Own the fresh empty-board reference required for live force processing."""

    def __init__(self, hardware, *, monotonic_ns=time.monotonic_ns) -> None:
        self._hardware = hardware
        self._monotonic_ns = monotonic_ns
        self.reference = None

    def acquire_for_new_session(self) -> PreflightCheck:
        try:
            self.reference = self._collect()
        except Exception:
            self.reference = None
            return PreflightCheck(
                "live_baseline", False, "E-CAL-002",
                "空载基线未完成，请确认压力垫无人站立后重新检查",
            )
        return PreflightCheck("live_baseline", True, operator_message="本次空载基线已采集")

    def _collect(self):
        configuration = self._hardware.baseline_configuration
        connection = self._hardware.connect_startup()
        frames = []
        first_ns = None
        last_signal = self._monotonic_ns()
        duration_ns = round(configuration.minimum_duration_seconds * 1_000_000_000)
        try:
            while first_ns is None or frames[-1].host_monotonic_ns - first_ns < duration_ns:
                chunk = connection.transport.read(16_384)
                if not chunk:
                    if self._monotonic_ns() - last_signal >= round(configuration.maximum_no_valid_signal_seconds * 1_000_000_000):
                        raise RuntimeError("no valid baseline signal")
                    continue
                for frame in connection.parser.feed(chunk):
                    if first_ns is None:
                        first_ns = frame.host_monotonic_ns
                    frames.append(frame)
                    last_signal = self._monotonic_ns()
        except TransportDisconnected as exc:
            raise RuntimeError("baseline transport disconnected") from exc
        finally:
            connection.transport.close()
        values = np.stack([frame.values.reshape(-1, order="F") for frame in frames])
        if float(np.median(values, axis=0).max()) > configuration.unloaded_frame_mean_max:
            raise RuntimeError("baseline is loaded")
        digest = hashlib.sha256()
        for frame in frames:
            digest.update(frame.host_monotonic_ns.to_bytes(8, "big", signed=False))
            digest.update(frame.values.tobytes(order="F"))
        window = UnloadedBaselineWindow(
            schema_version="unloaded-baseline-window/1",
            baseline_window_id=str(uuid4()), validation_run_id=str(uuid4()),
            validation_outcome="PASS", layout_digest=configuration.layout_digest,
            rules_version=configuration.rules_version, threshold_version=configuration.threshold_version,
            source_digest=digest.hexdigest(),
            samples=tuple(BaselineSample(frame.host_monotonic_ns, tuple(int(value) for value in frame.values.reshape(-1, order="F"))) for frame in frames),
        )
        return build_baseline_reference(window, minimum_duration_ns=duration_ns)
