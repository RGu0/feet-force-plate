from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class ReportKind(StrEnum):
    BASIC = "BASIC"
    CLOUD_COMPLETE = "CLOUD_COMPLETE"


@dataclass(frozen=True, slots=True)
class ReportContext:
    masked_subject_id: str
    institution_name: str
    site_name: str
    test_protocol_name: str
    tested_at: datetime


@dataclass(frozen=True, slots=True)
class PublicMetric:
    metric_id: str
    definition: str
    value: float
    unit: str

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "metric_id": self.metric_id,
            "definition": self.definition,
            "value": self.value,
            "unit": self.unit,
        }


@dataclass(frozen=True, slots=True)
class PublicSeries:
    name: str
    unit: str
    points: tuple[tuple[float, float], ...]
    line_style: str
    marker: str

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "unit": self.unit,
            "points": [[x, y] for x, y in self.points],
            "line_style": self.line_style,
            "marker": self.marker,
        }


@dataclass(frozen=True, slots=True)
class PublicFigure:
    figure_id: str
    title: str
    figure_type: str
    source_sample_rate_hz: float
    source_sampling_statement: str
    print_style: str
    alt_text: str
    series: tuple[PublicSeries, ...]
    matrix_shape: tuple[int, int] | None = None
    matrix_values: tuple[float, ...] = ()
    annotations: tuple[str, ...] = ()

    def to_public_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "figure_id": self.figure_id,
            "title": self.title,
            "figure_type": self.figure_type,
            "source_sample_rate_hz": self.source_sample_rate_hz,
            "source_sampling_statement": self.source_sampling_statement,
            "print_style": self.print_style,
            "alt_text": self.alt_text,
            "series": [series.to_public_dict() for series in self.series],
            "annotations": list(self.annotations),
        }
        if self.matrix_shape is not None:
            result["matrix"] = {
                "shape": list(self.matrix_shape),
                "values": list(self.matrix_values),
            }
        return result


@dataclass(frozen=True, slots=True)
class ReportDocument:
    report_id: str
    version_number: int
    kind: ReportKind
    generated_at: datetime
    context: ReportContext
    screening_summary: tuple[str, ...]
    risk_prompts: tuple[str, ...]
    core_metrics: tuple[PublicMetric, ...]
    professional_metrics: tuple[PublicMetric, ...]
    professional_figures: tuple[PublicFigure, ...]
    plain_language_guidance: tuple[str, ...]
    provenance: tuple[tuple[str, str], ...]

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "identity": {
                "report_id": self.report_id,
                "version": self.version_number,
                "kind": self.kind.value,
                "generated_at": self.generated_at.isoformat(),
                "subject_id": self.context.masked_subject_id,
                "test_protocol": self.context.test_protocol_name,
                "tested_at": self.context.tested_at.isoformat(),
            },
            "screening_summary": list(self.screening_summary),
            "risk_prompts": list(self.risk_prompts),
            "core_metrics": [metric.to_public_dict() for metric in self.core_metrics],
            "professional_parameters_and_curves": {
                "parameters": [
                    metric.to_public_dict() for metric in self.professional_metrics
                ],
                "curves": [
                    figure.to_public_dict() for figure in self.professional_figures
                ],
            },
            "plain_language_guidance": list(self.plain_language_guidance),
            "institution": {
                "name": self.context.institution_name,
                "site": self.context.site_name,
            },
            "provenance": dict(self.provenance),
        }


@dataclass(frozen=True, slots=True)
class ReportArtifact:
    object_key: str
    content_type: str
    size_bytes: int
    sha256: str
    renderer_version: str
    template_version: str


@dataclass(frozen=True, slots=True)
class ReportVersion:
    report_id: str
    tenant_id: str
    session_id: str
    version_number: int
    kind: ReportKind
    source_analysis_run_id: str | None
    report_schema_version: str
    document: ReportDocument | None
    document_sha256: str
    artifact: ReportArtifact
    generated_at: datetime


@dataclass(frozen=True, slots=True)
class ReportRecord:
    report_id: str
    tenant_id: str
    session_id: str
    latest_version: int
    versions: tuple[ReportVersion, ...]


@dataclass(frozen=True, slots=True)
class ReportPublishedEvent:
    event_type: str
    tenant_id: str
    report_id: str
    correlation_id: str
    version_number: int
    kind: ReportKind
