"""Uncalibrated four-stage V1 replay features for engineering debugging only."""

from __future__ import annotations

from datetime import datetime
import uuid

import numpy as np

from client.hardware_standardization.ports import DecodedHardwareFrame
from client.reporting.models import ReportMetric
from client.reporting.models import BasicReportDocument, ReportStatus
from client.reporting.copy import REPLAY_DEBUG_DISCLAIMER, REPLAY_DEBUG_SUMMARY
from client.local_analysis.service import ProcessingOutcome, ProcessingStatus
from client.local_analysis.models import (
    LocalAnalysisResult,
    LocalMetricValue,
    LocalQualityStatus,
    WithheldMetric,
)

_STAGES = (
    "BILATERAL_EYES_OPEN", "BILATERAL_EYES_CLOSED",
    "SEMI_TANDEM_LEFT_FORWARD", "SEMI_TANDEM_RIGHT_FORWARD",
)
_ALGORITHM_VERSION = "v1-replay-debug/1.0.0"
_PROTOCOL_ID = "standard-static-bilateral"
_PROTOCOL_VERSION = "v1-replay-debug/1.0.0"
_METRIC_LABELS = {
    "total": "总相对载荷",
    "left": "左侧相对负重",
    "path": "COP 路径",
    "sway": "ML/AP 摆动范围",
}


def analyze_v1_replay(
    stages: dict[str, tuple[DecodedHardwareFrame, ...]]
) -> LocalAnalysisResult:
    if tuple(stages) != _STAGES:
        raise ValueError("四段回放数据的顺序或阶段不完整")
    metrics: list[LocalMetricValue] = []
    final_heatmap: tuple[tuple[float, ...], ...] = ()
    for stage_id in _STAGES:
        frames = stages[stage_id]
        if len(frames) < 400:
            raise ValueError(f"{stage_id} 有效帧不足 20 秒")
        stack = np.asarray([frame.values for frame in frames], dtype=np.float64)
        if (
            stack.ndim != 3
            or 0 in stack.shape
            or not np.all(np.isfinite(stack))
            or np.any(stack < 0)
        ):
            raise ValueError(f"{stage_id} 含有无效压力矩阵")
        totals = stack.sum(axis=(1, 2))
        rows, columns = stack.shape[1:]
        left = stack[:, :, : columns // 2].sum(axis=(1, 2))
        x = np.arange(columns, dtype=np.float64)[None, None, :]
        y = np.arange(rows, dtype=np.float64)[None, :, None]
        cop_x = (stack * x).sum(axis=(1, 2)) / totals
        cop_y = (stack * y).sum(axis=(1, 2)) / totals
        path = np.hypot(np.diff(cop_x), np.diff(cop_y)).sum()
        metrics.extend(
            (
                LocalMetricValue(
                    f"{stage_id}:total",
                    float(totals.mean()),
                    "relative_count",
                    "v1-replay-debug/1",
                ),
                LocalMetricValue(
                    f"{stage_id}:left",
                    float((left / totals * 100).mean()),
                    "percent",
                    "v1-replay-debug/1",
                ),
                LocalMetricValue(
                    f"{stage_id}:path",
                    float(path),
                    "sensor_index",
                    "v1-replay-debug/1",
                ),
                LocalMetricValue(
                    f"{stage_id}:sway",
                    float(np.ptp(cop_x) + np.ptp(cop_y)),
                    "sensor_index",
                    "v1-replay-debug/1",
                ),
            )
        )
        if stage_id == _STAGES[-1]:
            mean = stack.mean(axis=0)
            final_heatmap = tuple(tuple(float(value) for value in row) for row in mean / mean.max())
    internal_metrics = tuple(metrics)
    return LocalAnalysisResult(
        result_version=1,
        algorithm_version=_ALGORITHM_VERSION,
        protocol_id=_PROTOCOL_ID,
        protocol_version=_PROTOCOL_VERSION,
        source_frame_count=sum(len(frames) for frames in stages.values()),
        quality_status=LocalQualityStatus.VALID,
        raw_count_heatmap=None,
        relative_heatmap=final_heatmap,
        customer_metrics=(),
        internal_metrics=internal_metrics,
        withheld_metrics=tuple(
            WithheldMetric(
                metric.key,
                "REPLAY_DEBUG_NOT_CUSTOMER_VALIDATED",
            )
            for metric in internal_metrics
        ),
    )


def _report_metrics(result: LocalAnalysisResult) -> tuple[ReportMetric, ...]:
    report_metrics: list[ReportMetric] = []
    for metric in result.internal_metrics:
        stage_id, metric_kind = metric.key.rsplit(":", 1)
        report_metrics.append(
            ReportMetric(
                metric.key,
                f"{stage_id} {_METRIC_LABELS[metric_kind]}",
                metric.value,
                metric.unit,
                metric.definition_version,
            )
        )
    return tuple(report_metrics)


class V1ReplayDebugProcessor:
    """Local-only report processor over the verified replay fixture."""

    def __init__(self, source, *, subject_display_id: str = "回放调试受试者", report_sink=None) -> None:
        self._source, self._subject_display_id, self._report_sink = source, subject_display_id, report_sink
        self._outcomes: dict[str, ProcessingOutcome] = {}

    def process(self, session_id: str) -> ProcessingOutcome:
        if session_id in self._outcomes:
            return self._outcomes[session_id]
        result = analyze_v1_replay({stage: tuple(self._source.frames_for(stage)) for stage in self._source.stage_ids})
        save_analysis = getattr(self._report_sink, "save_analysis_result", None)
        if callable(save_analysis):
            save_analysis(session_id, result)
        now = datetime.now()
        report = BasicReportDocument(
            report_id=f"replay-{uuid.uuid4().hex[:12]}", version=1,
            status=ReportStatus.BASIC_READY, kind="V1_REPLAY_DEBUG", session_id=session_id,
            analysis_result_id=f"v1-debug-{session_id}", subject_display_id=self._subject_display_id,
            captured_at=now, generated_at=now, protocol_id=result.protocol_id,
            protocol_version=result.protocol_version, metrics=_report_metrics(result),
            relative_heatmap=result.relative_heatmap,
            summary=REPLAY_DEBUG_SUMMARY,
            disclaimer=REPLAY_DEBUG_DISCLAIMER,
            provenance=tuple(
                value
                for value in (
                    result.algorithm_version,
                    self._source.fixture_sha256,
                    getattr(self._source, "processing_profile_version", None),
                )
                if value is not None
            ),
        )
        outcome = ProcessingOutcome(ProcessingStatus.BASIC_READY, None, report)
        if self._report_sink is not None:
            self._report_sink.save_report(report)
        self._outcomes[session_id] = outcome
        return outcome
