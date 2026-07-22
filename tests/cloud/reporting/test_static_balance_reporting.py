from __future__ import annotations

import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from cloud.analysis.feature_parameters import FeatureParameters
from cloud.analysis.features import extract_features
from cloud.analysis.physical_input import parse_physical_pressure_session
from cloud.analysis.risk_rules import QuestionnaireSnapshot, evaluate_screening_risk
from cloud.reporting.models import ReportContext, ReportKind
from cloud.reporting.pdf import MinimalPdfRenderer
from cloud.reporting.service import (
    InMemoryArtifactStore,
    InMemoryReportEventPublisher,
    InMemoryReportRepository,
)
from cloud.reporting.static_balance import (
    StaticBalanceCloudReportService,
    StaticBalanceReportBuilder,
)

sys.path.insert(0, str(Path(__file__).parents[1] / "analysis"))
from test_physical_features import _session_payload


def report_context() -> ReportContext:
    return ReportContext(
        masked_subject_id="**2781",
        institution_name="示例机构",
        site_name="主站点",
        test_protocol_name="V1 静态平衡筛查",
        tested_at=datetime(2026, 7, 20, 7, 30, tzinfo=UTC),
    )


def publish_service() -> tuple[StaticBalanceCloudReportService, InMemoryReportRepository, InMemoryArtifactStore]:
    repository = InMemoryReportRepository()
    repository.seed_basic(
        tenant_id="tenant-a",
        session_id="session-physical-1",
        report_id="report-a",
        document_sha256="d" * 64,
        artifact_sha256="e" * 64,
    )
    artifacts = InMemoryArtifactStore()
    service = StaticBalanceCloudReportService(
        repository=repository,
        artifact_store=artifacts,
        builder=StaticBalanceReportBuilder(),
        renderer=MinimalPdfRenderer(),
        publisher=InMemoryReportEventPublisher(),
    )
    return service, repository, artifacts


def analysis_input():
    session = parse_physical_pressure_session(_session_payload())
    features = extract_features(
        session,
        FeatureParameters(version="physical-features/test", lowpass_cutoff_hz=0.0),
    )
    risk = evaluate_screening_risk(
        session=session,
        features=features,
        questionnaire=QuestionnaireSnapshot(
            age_years=72,
            recent_fall_12m=True,
            recurrent_dizziness=False,
            medication_tags=frozenset(),
        ),
    )
    return session, features, risk


def test_static_balance_report_reuses_report_id_and_publishes_hashed_pdf() -> None:
    service, repository, artifacts = publish_service()
    session, features, risk = analysis_input()

    published = service.publish(
        tenant_id="tenant-a",
        session_id=session.session_id,
        source_analysis_run_id="run-physical-1",
        correlation_id="corr-physical-1",
        report_schema_version="static-balance-report/1.0",
        rule_set_version="fall-screen-rule-set/1.0",
        risk=risk,
        features=features,
        context=report_context(),
    )

    assert published.report_id == "report-a"
    assert published.version_number == 2
    assert published.kind is ReportKind.CLOUD_COMPLETE
    pdf = artifacts.get(published.artifact.object_key)
    assert pdf.startswith(b"%PDF-1.4")
    assert hashlib.sha256(pdf).hexdigest() == published.artifact.sha256
    assert repository.get_for_session("tenant-a", session.session_id).latest_version == 2


def test_customer_document_contains_one_score_and_no_sensitive_or_internal_fields() -> None:
    service, _, _ = publish_service()
    session, features, risk = analysis_input()

    published = service.publish(
        tenant_id="tenant-a",
        session_id=session.session_id,
        source_analysis_run_id="run-physical-1",
        correlation_id="corr-physical-1",
        report_schema_version="static-balance-report/1.0",
        rule_set_version="fall-screen-rule-set/1.0",
        risk=risk,
        features=features,
        context=report_context(),
    )
    public = published.document.to_public_dict()
    serialized = json.dumps(public, ensure_ascii=False)

    assert [metric["metric_id"] for metric in public["core_metrics"]] == ["balance_index"]
    assert public["core_metrics"][0]["value"] <= 59
    assert "RECENT_FALL_12M" not in serialized
    assert "MEDICATION_CATEGORY" not in serialized
    for forbidden in ("private_trace", "questionnaire", "error_code", "feature_cache_key", "stack_trace"):
        assert forbidden not in serialized


def test_duplicate_static_balance_publish_is_idempotent() -> None:
    service, repository, artifacts = publish_service()
    session, features, risk = analysis_input()
    kwargs = dict(
        tenant_id="tenant-a",
        session_id=session.session_id,
        source_analysis_run_id="run-physical-1",
        correlation_id="corr-physical-1",
        report_schema_version="static-balance-report/1.0",
        rule_set_version="fall-screen-rule-set/1.0",
        risk=risk,
        features=features,
        context=report_context(),
    )

    first = service.publish(**kwargs)
    second = service.publish(**kwargs)

    assert first == second
    assert repository.get_for_session("tenant-a", session.session_id).latest_version == 2
    assert artifacts.count() == 1
