from __future__ import annotations

from cloud.analysis.protocol_context import SubjectOrientation


def board_to_subject_coordinates(
    *,
    x_mm: float,
    y_mm: float,
    orientation: SubjectOrientation,
) -> tuple[float, float]:
    """Map board coordinates into a right-positive ML / forward-positive AP frame.

    The protocol's FORWARD stance faces the board's top edge.  LEFT_90 is the
    fixed left turn specified by the V1 protocol.  Translation is deliberately
    retained because it cancels from path, RMS, range, and ellipse metrics.
    """

    if orientation is SubjectOrientation.FORWARD:
        return x_mm, -y_mm
    if orientation is SubjectOrientation.LEFT_90:
        return -y_mm, -x_mm
    raise ValueError(f"unsupported subject orientation: {orientation!r}")
