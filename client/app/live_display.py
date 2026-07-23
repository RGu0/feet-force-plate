"""Port-based bridge from device latest frames to the P-07 display mailbox.

The bridge deliberately owns only UI projection state.  It never opens a
serial device, stores a raw frame, or decides session validity.  A hardware
adapter publishes immutable ``RawFrame`` objects into its own latest-only
mailbox; the application polls that port and produces an independent
``DisplayFrame`` for the Qt view.
"""

from __future__ import annotations

from typing import Protocol

from client.device.protocol import RawFrame
from client.local_analysis.display import DisplayFrame, LatestDisplayFrameMailbox, build_display_frame


class LatestRawFramePort(Protocol):
    """Read-only application boundary over a hardware latest-frame mailbox."""

    def read(self) -> RawFrame | None: ...


class LiveDisplayProjection:
    """Project each newer hardware frame once, without retaining raw matrices."""

    def __init__(
        self,
        *,
        source: LatestRawFramePort,
        destination: LatestDisplayFrameMailbox,
    ) -> None:
        self._source = source
        self._destination = destination
        self._last_source_index = -1
        self._cop_trail: tuple[tuple[float, float], ...] = ()
        self._total_trend: tuple[float, ...] = ()

    @property
    def last_source_index(self) -> int:
        return self._last_source_index

    def reset(self) -> None:
        """Forget per-session UI history before a new source-index sequence."""
        self._last_source_index = -1
        self._cop_trail = ()
        self._total_trend = ()

    def poll(self) -> DisplayFrame | None:
        """Publish a new display copy, or ``None`` when the device frame is unchanged."""
        raw_frame = self._source.read()
        if raw_frame is None or raw_frame.source_index <= self._last_source_index:
            return None
        display_frame = build_display_frame(
            raw_frame.values,
            sequence=raw_frame.source_index,
            captured_monotonic_seconds=raw_frame.host_monotonic_ns / 1_000_000_000,
            cop_trail=self._cop_trail,
            total_trend=self._total_trend,
        )
        self._last_source_index = raw_frame.source_index
        self._cop_trail = display_frame.cop_trail
        self._total_trend = display_frame.total_trend
        self._destination.publish(display_frame)
        return display_frame
