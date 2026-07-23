"""Deterministic JSON-compatible representation of physical-array sessions."""

from __future__ import annotations

from .models import PhysicalArraySession


def physical_array_session_to_dict(session: PhysicalArraySession) -> dict[str, object]:
    """Serialize only board-plane values and explicit validation/provenance fields."""

    return {
        "schema_version": session.schema_version,
        "session_id": session.session_id,
        "coordinate_frame": session.coordinate_frame,
        "coordinate_unit": session.coordinate_unit,
        "raw_value_unit": session.raw_value_unit,
        "relative_value_unit": session.relative_value_unit,
        "force_unit": session.force_unit,
        "measurement_profile": {
            "profile_version": session.measurement_profile.profile_version,
            "geometry_validation": session.measurement_profile.geometry_validation,
            "baseline_validation": session.measurement_profile.baseline_validation,
            "force_validation": session.measurement_profile.force_validation,
            "timing_validation": session.measurement_profile.timing_validation,
            "active_area_validation": session.measurement_profile.active_area_validation,
            "uncertainty_profile_version": session.measurement_profile.uncertainty_profile_version,
        },
        "uncertainty": {
            "profile_version": session.uncertainty.profile_version,
            "coordinate_mm": session.uncertainty.coordinate_mm,
            "relative_count": session.uncertainty.relative_count,
            "force_n": session.uncertainty.force_n,
            "timing_s": session.uncertainty.timing_s,
            "validation": session.uncertainty.validation,
        },
        "cells": [
            {
                "cell_id": cell.cell_id,
                "source_index": cell.source_index,
                "board_x_mm": cell.board_x_mm,
                "board_y_mm": cell.board_y_mm,
                "nominal_active_area_mm2": cell.nominal_active_area_mm2,
                "status": cell.status.value,
            }
            for cell in session.cells
        ],
        "frames": [
            {
                "timestamp_s": frame.timestamp_s,
                "raw_count": list(frame.raw_count),
                "zero_corrected_count": (
                    None
                    if frame.zero_corrected_count is None
                    else list(frame.zero_corrected_count)
                ),
                "relative_load_count": (
                    None
                    if frame.relative_load_count is None
                    else list(frame.relative_load_count)
                ),
                "normal_force_n": list(frame.normal_force_n),
                "quality": frame.quality.value,
                "quality_flags": sorted(frame.quality_flags),
                "raw_voltage_v": (
                    None if frame.raw_voltage_v is None else list(frame.raw_voltage_v)
                ),
                "zero_corrected_voltage_v": (
                    None
                    if frame.zero_corrected_voltage_v is None
                    else list(frame.zero_corrected_voltage_v)
                ),
                "provisional_force_n": (
                    None
                    if frame.provisional_force_n is None
                    else list(frame.provisional_force_n)
                ),
            }
            for frame in session.frames
        ],
        "provenance": {
            "adapter_version": session.adapter_version,
            "geometry_version": session.geometry_version,
            "source_schema_version": session.source_schema_version,
        },
    }
