"""Offline local projection of the canonical physical feature pipeline.

This module consumes only the public ``estimated-force-session/1.0`` contract.
It intentionally exposes the canonical physical features as internal supporting
metrics: customer release remains the cloud capability gate's responsibility.
"""

from __future__ import annotations

from dataclasses import fields
from pathlib import Path

from client.hardware_standardization.public_export import PhysicalPressureSession
from client.spool.session_commit import read_committed_physical_session
from client.spool.state_store import KeyProvider, StateStore
from cloud.analysis.feature_parameters import FeatureParameters
from cloud.analysis.features import StageFeatureSet, extract_features
from cloud.analysis.physical_input import parse_physical_pressure_session
from cloud.analysis.protocol_context import StaticBalanceProtocolContext

from .models import (
    LocalAnalysisResult,
    LocalMetricValue,
    LocalQualityStatus,
    WithheldMetric,
)


_RESULT_VERSION = 1
_ALGORITHM_VERSION = "local-physical-analysis/1.0"
_PROTOCOL_ID = "standard-static-balance"
_WITHHELD_REASON = "LOCAL_PHYSICAL_FEATURE_NOT_CUSTOMER_RELEASED"
_NON_SCALAR_STAGE_FIELDS = frozenset(
    {
        "stage_id",
        "contact_area_variation_mm2",
        "timestamps_s",
        "cop_ml_mm",
        "cop_ap_mm",
    }
)
_SCALAR_STAGE_FIELDS = tuple(
    field.name
    for field in fields(StageFeatureSet)
    if field.name not in _NON_SCALAR_STAGE_FIELDS
)
_UNITS = {
    "completion_time_s": "s",
    "cop_path_mm": "mm",
    "mean_velocity_mm_s": "mm/s",
    "ap_mean_velocity_mm_s": "mm/s",
    "ml_mean_velocity_mm_s": "mm/s",
    "ap_rms_mm": "mm",
    "ml_rms_mm": "mm",
    "ap_range_90_mm": "mm",
    "ml_range_90_mm": "mm",
    "ellipse_area_95_mm2": "mm2",
    "total_force_cv": "ratio",
    "valid_frame_count": "count",
    "total_frame_count": "count",
    "gap_count": "count",
}


def analyze_committed_physical_session(
    root: str | Path,
    *,
    session_id: str,
    store: StateStore,
    key_provider: KeyProvider,
    protocol_context: StaticBalanceProtocolContext,
    parameters: FeatureParameters,
) -> LocalAnalysisResult:
    """Read one CLOSED/VALID encrypted session and analyze it entirely locally."""

    session = read_committed_physical_session(
        root,
        session_id=session_id,
        store=store,
        key_provider=key_provider,
    )
    return analyze_physical_session(session, protocol_context, parameters)


def analyze_physical_session(
    session: PhysicalPressureSession,
    protocol_context: StaticBalanceProtocolContext,
    parameters: FeatureParameters,
) -> LocalAnalysisResult:
    """Generate a versioned local supporting result without any network call."""

    if session.session_id != protocol_context.session_id:
        raise ValueError("physical session and protocol context session identity mismatch")
    physical_input = parse_physical_pressure_session(session.to_dict())
    feature_set = extract_features(physical_input, protocol_context, parameters)
    definition_version = "|".join(
        (
            feature_set.pipeline_version,
            parameters.version,
            feature_set.parameters_sha256,
        )
    )
    metrics = tuple(
        LocalMetricValue(
            key=f"{stage.stage_id.value}:{field_name}",
            value=float(getattr(stage, field_name)),
            unit=_UNITS[field_name],
            definition_version=definition_version,
        )
        for stage in feature_set.stages
        for field_name in _SCALAR_STAGE_FIELDS
    )
    algorithm_version = "|".join(
        (
            _ALGORITHM_VERSION,
            feature_set.pipeline_version,
            parameters.version,
            feature_set.parameters_sha256,
        )
    )
    return LocalAnalysisResult(
        result_version=_RESULT_VERSION,
        algorithm_version=algorithm_version,
        protocol_id=_PROTOCOL_ID,
        protocol_version=protocol_context.protocol_version,
        source_frame_count=len(session.frames),
        quality_status=LocalQualityStatus.VALID,
        raw_count_heatmap=None,
        relative_heatmap=None,
        customer_metrics=(),
        internal_metrics=metrics,
        withheld_metrics=tuple(
            WithheldMetric(metric.key, _WITHHELD_REASON) for metric in metrics
        ),
    )
