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

    @classmethod
    def from_json(cls, payload: str) -> "BasicReportDocument":
        value = json.loads(payload)
        return cls(
            report_id=value["report_id"],
            version=int(value["version"]),
            status=ReportStatus(value["status"]),
            kind=value["kind"],
            session_id=value["session_id"],
            analysis_result_id=value["analysis_result_id"],
            subject_display_id=value["subject_display_id"],
            captured_at=datetime.fromisoformat(value["captured_at"]),
            generated_at=datetime.fromisoformat(value["generated_at"]),
            protocol_id=value["protocol_id"],
            protocol_version=value["protocol_version"],
            metrics=tuple(ReportMetric(**metric) for metric in value["metrics"]),
            relative_heatmap=tuple(
                tuple(float(cell) for cell in row)
                for row in value["relative_heatmap"]
            ),
            summary=value["summary"],
            disclaimer=value["disclaimer"],
            provenance=tuple(value["provenance"]),
        )
