from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class ReportStatus(StrEnum):
    BASIC_READY = "BASIC_READY"
    FULL_READY = "FULL_READY"


@dataclass(frozen=True, slots=True)
class ReportMetric:
    key: str
    label: str
    value: float
    unit: str
    definition_version: str


@dataclass(frozen=True, slots=True)
class BasicReportDocument:
    report_id: str
    version: int
    status: ReportStatus
    kind: str
    session_id: str
    analysis_result_id: str
    subject_display_id: str
    captured_at: datetime
    generated_at: datetime
    protocol_id: str
    protocol_version: str
    metrics: tuple[ReportMetric, ...]
    relative_heatmap: tuple[tuple[float, ...], ...]
    summary: str
    disclaimer: str
    provenance: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "report_id": self.report_id,
            "version": self.version,
            "status": self.status.value,
            "kind": self.kind,
            "session_id": self.session_id,
            "analysis_result_id": self.analysis_result_id,
            "subject_display_id": self.subject_display_id,
            "captured_at": self.captured_at.isoformat(),
            "generated_at": self.generated_at.isoformat(),
            "protocol_id": self.protocol_id,
            "protocol_version": self.protocol_version,
            "metrics": [
                {
                    "key": metric.key,
                    "label": metric.label,
                    "value": metric.value,
                    "unit": metric.unit,
                    "definition_version": metric.definition_version,
                }
                for metric in self.metrics
            ],
            "relative_heatmap": self.relative_heatmap,
            "summary": self.summary,
            "disclaimer": self.disclaimer,
            "provenance": self.provenance,
        }

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
