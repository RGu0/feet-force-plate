"""Ports that keep baseline acquisition and hardware adaptation out of core logic."""

from __future__ import annotations

from typing import Protocol

from .models import UnloadedBaselineWindow


class UnloadedBaselineWindowProvider(Protocol):
    """Supplies a previously captured immutable unloaded window by reference."""

    def get(self, baseline_window_id: str) -> UnloadedBaselineWindow: ...
