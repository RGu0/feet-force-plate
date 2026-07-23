from __future__ import annotations

import numpy as np
import pytest

from scripts.evaluate_temporal_denoising import centered_moving_mean


def test_centered_moving_mean_reduces_an_impulse_without_changing_shape() -> None:
    frames = np.zeros((5, 1, 1), dtype=float)
    frames[2, 0, 0] = 9.0

    result = centered_moving_mean(frames, 3)

    assert result.shape == frames.shape
    assert result[:, 0, 0] == pytest.approx([0.0, 3.0, 3.0, 3.0, 0.0])


def test_centered_moving_mean_requires_a_positive_odd_window() -> None:
    frames = np.zeros((3, 1, 1), dtype=float)

    with pytest.raises(ValueError, match="positive odd"):
        centered_moving_mean(frames, 2)
