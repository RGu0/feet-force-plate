from __future__ import annotations

import json
from datetime import UTC, datetime

from client.reporting.models import (
    BasicReportDocument,
    ReportMetric,
    ReportStage,
    ReportStatus,
)


def test_basic_report_document_is_serializable_and_contains_no_diagnostic_claim() -> None:
    report = BasicReportDocument(
        report_id="report-1",
        version=1,
        status=ReportStatus.BASIC_READY,
        kind="BASIC",
        session_id="session-1",
        analysis_result_id="analysis-1",
        subject_display_id="受试者 **1234",
        captured_at=datetime(2026, 7, 20, 10, 0, tzinfo=UTC),
        generated_at=datetime(2026, 7, 20, 10, 1, tzinfo=UTC),
        protocol_id="standard-static-bilateral",
        protocol_version="1.0.0-pilot",
        metrics=(
            ReportMetric(
                key="left_load_percent",
                label="左侧相对负重",
                value=50.0,
                unit="percent",
                definition_version="1.0.0",
            ),
        ),
        relative_heatmap=((0.0, 1.0),),
        summary="基础相对压力分布已生成。",
        disclaimer="本报告用于健康筛查与风险提示，不作疾病诊断。",
        provenance=("local-basic/1.0.0", "report-schema/2.0.0"),
        stages=(
            ReportStage(
                stage_id="BILATERAL_EYES_OPEN",
                title="第一段：并足睁眼",
                relative_heatmap=((0.0, 1.0),),
                metrics=(
                    ReportMetric(
                        "cop_path_mm",
                        "COP 路径长度",
                        12.5,
                        "mm",
                        "2.0.0",
                    ),
                ),
            ),
        ),
    )

    payload = json.loads(report.to_json())

    assert payload["report_id"] == "report-1"
    assert payload["version"] == 1
    assert payload["status"] == "BASIC_READY"
    assert "不作疾病诊断" in payload["disclaimer"]
    assert "quality" not in payload
    assert "stack" not in report.to_json().lower()
    restored = BasicReportDocument.from_json(report.to_json())
    assert restored == report
    assert restored.stages[0].metric_map["cop_path_mm"].value == 12.5
