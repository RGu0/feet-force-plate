from __future__ import annotations

from dataclasses import fields
from pathlib import Path

import numpy as np
import pytest

from client.device.protocol import RawFrame
from client.hardware_standardization.models import (
    CellStatus,
    FrameQuality,
    MeasurementProfile,
    MeasurementUncertainty,
    PhysicalArrayCell,
    PhysicalArrayFrame,
    PhysicalArraySession,
)
from client.hardware_standardization.public_export import (
    PhysicalPressureFrame,
    PhysicalPressurePoint,
    PhysicalPressureSession,
)
from client.local_analysis.models import LocalAnalysisResult, LocalQualityStatus
from client.local_analysis.physical import (
    analyze_committed_physical_session,
    analyze_physical_session,
)
from client.spool.session_commit import ValidSessionStager
from client.spool.state_store import SensitiveBlobCodec, StateStore
from cloud.analysis.feature_parameters import FeatureParameters
from cloud.analysis.features import StageFeatureSet, extract_features
from cloud.analysis.models import ValidationStatus
from cloud.analysis.physical_gates import PhysicalMetricDescriptor
from cloud.analysis.physical_input import (
    PhysicalInputValidationStatus,
    parse_physical_pressure_session,
)
from cloud.analysis.physical_orchestrator import (
    CompleteSessionEvent,
    InMemoryPhysicalSessionLoader,
    InMemoryQuestionnaireLoader,
    PhysicalAnalysisOrchestrator,
)
from cloud.analysis.physical_runs import (
    InMemoryPhysicalAnalysisRepository,
    PhysicalRunStatus,
)
from cloud.analysis.protocol_context import (
    CompletionStatus,
    ForwardFoot,
    StageId,
    StageWindow,
    StaticBalanceProtocolContext,
    StopReason,
    SubjectOrientation,
    protocol_context_sha256,
)
from cloud.analysis.risk_rules import (
    QuestionnaireSnapshot,
    questionnaire_snapshot_sha256,
)


def _stage(
    stage_id: StageId,
    start_s: float,
    *,
    orientation: SubjectOrientation,
    foot: ForwardFoot,
) -> StageWindow:
    return StageWindow(
        stage_id=stage_id,
        start_s=start_s,
        end_s=start_s + 20.0,
        completion_status=CompletionStatus.COMPLETED,
        actual_completion_s=20.0,
        subject_orientation=orientation,
        forward_foot=foot,
        step_count=0,
        moved_feet=False,
        touched_rail=False,
        staff_supported=False,
        near_fall=False,
        eyes_opened_early=False,
        stop_reason=StopReason.NONE,
    )


def _protocol() -> StaticBalanceProtocolContext:
    return StaticBalanceProtocolContext(
        session_id="ray-85-physical",
        protocol_version="static-balance/1",
        stages=(
            _stage(
                StageId.BILATERAL_EYES_OPEN,
                0.0,
                orientation=SubjectOrientation.FORWARD,
                foot=ForwardFoot.NONE,
            ),
            _stage(
                StageId.BILATERAL_EYES_CLOSED,
                20.0,
                orientation=SubjectOrientation.FORWARD,
                foot=ForwardFoot.NONE,
            ),
            _stage(
                StageId.SEMI_TANDEM_LEFT_FORWARD,
                40.0,
                orientation=SubjectOrientation.LEFT_90,
                foot=ForwardFoot.LEFT,
            ),
            _stage(
                StageId.SEMI_TANDEM_RIGHT_FORWARD,
                60.0,
                orientation=SubjectOrientation.LEFT_90,
                foot=ForwardFoot.RIGHT,
            ),
        ),
    )


def _physical_session() -> PhysicalPressureSession:
    points = (
        PhysicalPressurePoint("a", -40.0, -40.0),
        PhysicalPressurePoint("b", 40.0, -40.0),
        PhysicalPressurePoint("c", -40.0, 40.0),
        PhysicalPressurePoint("d", 40.0, 40.0),
    )
    frames = []
    for index in range(80 * 20 + 1):
        timestamp_s = index / 20.0
        stage_index = min(int(timestamp_s // 20.0), 3)
        local = timestamp_s % 20.0
        shift = (stage_index + 1) * local / 20.0
        frames.append(
            PhysicalPressureFrame(
                timestamp_s=timestamp_s,
                estimated_force_n=(
                    25.0 - shift,
                    25.0 + shift,
                    25.0 - shift,
                    25.0 + shift,
                ),
            )
        )
    return PhysicalPressureSession(
        session_id="ray-85-physical",
        points=points,
        frames=tuple(frames),
    )


_SCALAR_STAGE_FIELDS = tuple(
    field.name
    for field in fields(StageFeatureSet)
    if field.name
    not in {
        "stage_id",
        "contact_area_variation_mm2",
        "timestamps_s",
        "cop_ml_mm",
        "cop_ap_mm",
    }
)


class _KeyProvider:
    def get_key(self) -> bytes:
        return b"r" * 32


def _private_session(public: PhysicalPressureSession) -> PhysicalArraySession:
    cells = tuple(
        PhysicalArrayCell(
            cell_id=point.point_id,
            source_index=index,
            board_x_mm=point.board_x_mm,
            board_y_mm=point.board_y_mm,
            nominal_active_area_mm2=None,
            status=CellStatus.ACTIVE,
        )
        for index, point in enumerate(public.points)
    )
    frames = tuple(
        PhysicalArrayFrame(
            timestamp_s=frame.timestamp_s,
            raw_count=frame.estimated_force_n,
            zero_corrected_count=frame.estimated_force_n,
            relative_load_count=frame.estimated_force_n,
            quality=FrameQuality.VALID,
            quality_flags=frozenset(),
            estimated_force_n=frame.estimated_force_n,
        )
        for frame in public.frames
    )
    return PhysicalArraySession(
        schema_version="estimated-force-session/1.0",
        session_id=public.session_id,
        coordinate_frame=public.coordinate_frame,
        coordinate_unit=public.coordinate_unit,
        raw_value_unit="count",
        relative_value_unit="relative_count",
        force_unit=public.force_unit,
        measurement_profile=MeasurementProfile(
            profile_version="ray-85-test/1",
            geometry_validation="TEST",
            baseline_validation="TEST",
            force_validation="MVP_SCREENING_ESTIMATED_TEST",
            timing_validation="TEST",
            active_area_validation="UNAVAILABLE",
            uncertainty_profile_version="ray-85-test/1",
        ),
        uncertainty=MeasurementUncertainty(
            profile_version="ray-85-test/1",
            coordinate_mm=None,
            relative_count=None,
            force_n=None,
            timing_s=None,
            validation="TEST_ONLY",
        ),
        cells=cells,
        frames=frames,
        adapter_version="ray-85-test/1",
        geometry_version="ray-85-test/1",
        source_schema_version="ray-85-test/1",
    )


def test_public_physical_session_generates_versioned_internal_local_result() -> None:
    session = _physical_session()
    parameters = FeatureParameters(
        version="physical-features/ray-85-local-test",
        despike_window_samples=1,
        lowpass_cutoff_hz=0.0,
    )

    result = analyze_physical_session(session, _protocol(), parameters)

    assert isinstance(result, LocalAnalysisResult)
    assert result.result_version == 1
    assert result.algorithm_version.startswith("local-physical-analysis/1.0|")
    assert result.protocol_id == "standard-static-balance"
    assert result.protocol_version == "static-balance/1"
    assert result.source_frame_count == 1_601
    assert result.quality_status is LocalQualityStatus.VALID
    assert result.raw_count_heatmap is None
    assert result.customer_metrics == ()
    assert len(result.internal_metrics) == 4 * len(_SCALAR_STAGE_FIELDS)
    assert len(result.withheld_metrics) == len(result.internal_metrics)
    assert set(result.withheld_reason_map.values()) == {
        "LOCAL_PHYSICAL_FEATURE_NOT_CUSTOMER_RELEASED"
    }


def test_local_metrics_are_the_exact_features_used_by_cloud_physical_pipeline() -> None:
    local_session = _physical_session()
    protocol = _protocol()
    parameters = FeatureParameters(
        version="physical-features/ray-85-alignment-test",
        despike_window_samples=1,
        lowpass_cutoff_hz=0.0,
    )

    local = analyze_physical_session(local_session, protocol, parameters)
    cloud_features = extract_features(
        parse_physical_pressure_session(local_session.to_dict()),
        protocol,
        parameters,
    )

    for stage in cloud_features.stages:
        for field_name in _SCALAR_STAGE_FIELDS:
            metric = local.internal_metric_map[f"{stage.stage_id.value}:{field_name}"]
            assert metric.value == pytest.approx(float(getattr(stage, field_name)), abs=1e-12)
            assert metric.definition_version.endswith(cloud_features.parameters_sha256)


def test_local_result_aligns_with_same_input_cloud_orchestrator_run() -> None:
    local_session = _physical_session()
    cloud_session = parse_physical_pressure_session(local_session.to_dict())
    protocol = _protocol()
    parameters = FeatureParameters(
        version="physical-features/ray-85-orchestrator-alignment",
        despike_window_samples=1,
        lowpass_cutoff_hz=0.0,
    )
    canonical = extract_features(cloud_session, protocol, parameters)
    questionnaire = QuestionnaireSnapshot(
        age_years=72,
        recent_fall_12m=False,
        recurrent_dizziness=False,
        medication_tags=frozenset(),
    )
    event = CompleteSessionEvent(
        event_id="event-ray-85",
        event_type="INGESTED_COMPLETE",
        tenant_id="tenant-ray-85",
        session_id=local_session.session_id,
        manifest_sha256="a" * 64,
        hardware_adapter_version="adapter/ray-85",
        input_schema_version=local_session.schema_version,
        measurement_conformance_version="measurement/ray-85",
        calibration_profile_version="calibration/ray-85",
        uncertainty_profile_version="uncertainty/ray-85",
        input_validation_status=PhysicalInputValidationStatus.VALIDATED,
        test_protocol_version=protocol.protocol_version,
        protocol_context=protocol,
        protocol_context_sha256=protocol_context_sha256(protocol),
        feature_pipeline_version=canonical.pipeline_version,
        rule_set_version="rules/ray-85",
        reference_population_id="reference-ray-85",
        reference_artifact_sha256="b" * 64,
        questionnaire_snapshot_sha256=questionnaire_snapshot_sha256(questionnaire),
        result_schema_version="screening-result/1.0",
        correlation_id="correlation-ray-85",
    )
    orchestrator = PhysicalAnalysisOrchestrator(
        loader=InMemoryPhysicalSessionLoader(cloud_session),
        repository=InMemoryPhysicalAnalysisRepository(),
        parameters=parameters,
        release_descriptor=PhysicalMetricDescriptor(
            metric_id="ellipse_area_95_mm2",
            unit="mm2",
            definition="COP 95 percent ellipse area",
            input_schema_version=local_session.schema_version,
            measurement_conformance_version=event.measurement_conformance_version,
            calibration_profile_version=event.calibration_profile_version,
            uncertainty_profile_version=event.uncertainty_profile_version,
            protocol_version=protocol.protocol_version,
            feature_pipeline_version=canonical.pipeline_version,
            feature_parameters_sha256=canonical.parameters_sha256,
            algorithm_version=event.rule_set_version,
            validation_status=ValidationStatus.APPROVED,
            reference_artifact_sha256=event.reference_artifact_sha256,
            approved_adapter_version=event.hardware_adapter_version,
        ),
        questionnaire_loader=InMemoryQuestionnaireLoader(questionnaire),
    )

    local = analyze_physical_session(local_session, protocol, parameters)
    cloud_run = orchestrator.handle(event)

    assert cloud_run.status is PhysicalRunStatus.SUCCEEDED
    assert cloud_run.feature_set is not None
    for stage in cloud_run.feature_set.stages:
        for field_name in _SCALAR_STAGE_FIELDS:
            assert local.internal_metric_map[
                f"{stage.stage_id.value}:{field_name}"
            ].value == pytest.approx(float(getattr(stage, field_name)), abs=1e-12)


def test_protocol_identity_mismatch_fails_before_local_result() -> None:
    protocol = _protocol()
    mismatched = StaticBalanceProtocolContext(
        session_id="another-session",
        protocol_version=protocol.protocol_version,
        stages=protocol.stages,
    )

    with pytest.raises(ValueError, match="session identity"):
        analyze_physical_session(
            _physical_session(),
            mismatched,
            FeatureParameters(despike_window_samples=1, lowpass_cutoff_hz=0.0),
        )


def test_committed_local_source_is_composed_directly_without_an_upload_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _physical_session()
    observed: dict[str, object] = {}

    def read_committed(root, *, session_id, store, key_provider):
        observed.update(
            root=root,
            session_id=session_id,
            store=store,
            key_provider=key_provider,
        )
        return session

    monkeypatch.setattr(
        "client.local_analysis.physical.read_committed_physical_session",
        read_committed,
    )
    store = object()
    key_provider = object()
    result = analyze_committed_physical_session(
        "/local-spool",
        session_id=session.session_id,
        store=store,
        key_provider=key_provider,
        protocol_context=_protocol(),
        parameters=FeatureParameters(
            version="physical-features/ray-85-committed-test",
            despike_window_samples=1,
            lowpass_cutoff_hz=0.0,
        ),
    )

    assert result.source_frame_count == 1_601
    assert observed == {
        "root": "/local-spool",
        "session_id": session.session_id,
        "store": store,
        "key_provider": key_provider,
    }


def test_closed_valid_encrypted_artifact_runs_through_local_physical_analysis(
    tmp_path: Path,
) -> None:
    public = _physical_session()
    key_provider = _KeyProvider()
    store = StateStore(
        tmp_path / "state.sqlite3",
        SensitiveBlobCodec(key_provider),
    )
    store.put_subject_ref("subject-ray-85", b"opaque")
    stager = ValidSessionStager(
        tmp_path / "data",
        session_id=public.session_id,
        key_provider=key_provider,
        store=store,
        subject_uuid="subject-ray-85",
        consent_id=None,
        versions={"protocol": "static-balance/1", "quality": "ray-85-test/1"},
        started_at_ns=1_000_000_000,
    )
    raw_values = np.zeros((48, 64), dtype=np.uint8)
    raw_values.setflags(write=False)
    stager.append(
        RawFrame(
            values=raw_values,
            host_monotonic_ns=1_000_000_000,
            host_wall_time_ns=1_000_000_000,
            source_index=0,
            device_frame_seq=None,
            device_timestamp_ns=None,
            quality_flags=frozenset(),
        )
    )
    stager.stage_derived_observation(_private_session(public))
    stager.commit_valid(ended_at_ns=81_000_000_000)

    try:
        result = analyze_committed_physical_session(
            tmp_path / "data",
            session_id=public.session_id,
            store=store,
            key_provider=key_provider,
            protocol_context=_protocol(),
            parameters=FeatureParameters(
                version="physical-features/ray-85-storage-integration",
                despike_window_samples=1,
                lowpass_cutoff_hz=0.0,
            ),
        )
    finally:
        store.close()

    assert result.source_frame_count == 1_601
    assert result.quality_status is LocalQualityStatus.VALID
    assert len(result.internal_metrics) == 56
    assert result.customer_metrics == ()
