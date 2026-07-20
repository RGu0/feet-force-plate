from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from client.workflow.protocol import (
    FeatureFlags,
    ProtocolCatalog,
    ProtocolParadigm,
    ProtocolUnavailable,
    ProtocolValidationStatus,
    ReferenceRangeApprovalStatus,
    ReferenceRangeDefinition,
    default_standard_protocol,
)


def test_default_protocol_is_versioned_and_captures_start_end_quality_and_prompts() -> None:
    protocol = default_standard_protocol()

    assert protocol.protocol_id == "standard-static-bilateral"
    assert protocol.version == "1.0.0-pilot"
    assert protocol.paradigm is ProtocolParadigm.STANDARD_BILATERAL
    assert protocol.acquisition_duration_seconds == 30
    assert protocol.start_condition.stable_hold_seconds == 3
    assert protocol.start_condition.requires_minimum_contact
    assert protocol.start_condition.requires_valid_area
    assert protocol.end_condition.ends_on_duration
    assert protocol.end_condition.operator_stop_marks_incomplete
    assert protocol.quality_gate.version
    assert "valid_duration" in protocol.quality_gate.required_checks
    assert protocol.prompts.position_text == "双脚自然站立，保持身体放松"
    assert protocol.prompts.audio_enabled is False
    assert protocol.validation_status is ProtocolValidationStatus.PILOT_REQUIRED


def test_extended_paradigm_requires_both_feature_flag_and_validation() -> None:
    standard = default_standard_protocol()
    unvalidated_single_leg = replace(
        standard,
        protocol_id="single-leg-static",
        paradigm=ProtocolParadigm.SINGLE_LEG,
    )
    catalog = ProtocolCatalog((standard, unvalidated_single_leg))

    with pytest.raises(ProtocolUnavailable):
        catalog.select(
            ProtocolParadigm.SINGLE_LEG,
            FeatureFlags(enabled_protocol_ids=()),
        )
    with pytest.raises(ProtocolUnavailable):
        catalog.select(
            ProtocolParadigm.SINGLE_LEG,
            FeatureFlags(enabled_protocol_ids=("single-leg-static",)),
        )

    validated = replace(
        unvalidated_single_leg,
        validation_status=ProtocolValidationStatus.VALIDATED,
    )
    selected = ProtocolCatalog((standard, validated)).select(
        ProtocolParadigm.SINGLE_LEG,
        FeatureFlags(enabled_protocol_ids=("single-leg-static",)),
    )
    assert selected.protocol_id == "single-leg-static"


def test_reference_range_is_publishable_only_with_population_source_version_and_approval() -> None:
    draft = ReferenceRangeDefinition(
        range_id="balance-static-adult",
        version="draft-1",
        applicable_population=None,
        source=None,
        approval_status=ReferenceRangeApprovalStatus.DRAFT,
    )
    assert not draft.is_publishable

    approved = ReferenceRangeDefinition(
        range_id="balance-static-adult",
        version="1.0.0",
        applicable_population="validated adult pilot cohort",
        source="validation-study-2026-01",
        approval_status=ReferenceRangeApprovalStatus.APPROVED,
        approved_by="clinical-review-board",
        approved_at=datetime(2026, 7, 20, tzinfo=UTC),
    )
    assert approved.is_publishable
