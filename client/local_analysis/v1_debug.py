"""Uncalibrated four-stage V1 replay features for engineering debugging only."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import uuid

import numpy as np

from client.device.protocol import RawFrame
from client.reporting.models import ReportMetric
from client.reporting.models import BasicReportDocument, ReportStatus
from client.reporting.copy import REPLAY_DEBUG_DISCLAIMER, REPLAY_DEBUG_SUMMARY
from client.local_analysis.service import ProcessingOutcome, ProcessingStatus

_STAGES = (
    "BILATERAL_EYES_OPEN", "BILATERAL_EYES_CLOSED",
    "SEMI_TANDEM_LEFT_FORWARD", "SEMI_TANDEM_RIGHT_FORWARD",
)


@dataclass(frozen=True, slots=True)
class V1DebugResult:
    status: str
    metrics: tuple[ReportMetric, ...]
    relative_heatmap: tuple[tuple[float, ...], ...]
    score: None = None
    risk_level: None = None


def analyze_v1_replay(stages: dict[str, tuple[RawFrame, ...]]) -> V1DebugResult:
    if tuple(stages) != _STAGES:
        raise ValueError("四段回放数据的顺序或阶段不完整")
    metrics: list[ReportMetric] = []
    final_heatmap: tuple[tuple[float, ...], ...] = ()
    for stage_id in _STAGES:
        frames = stages[stage_id]
        if len(frames) < 400:
            raise ValueError(f"{stage_id} 有效帧不足 20 秒")
        stack = np.asarray([frame.values for frame in frames], dtype=np.float64)
        if stack.shape[1:] != (48, 64) or not np.all(np.isfinite(stack)) or np.any(stack < 0):
            raise ValueError(f"{stage_id} 含有无效压力矩阵")
        totals = stack.sum(axis=(1, 2))
        left = stack[:, :, :32].sum(axis=(1, 2))
        right = stack[:, :, 32:].sum(axis=(1, 2))
        x = np.arange(64, dtype=np.float64)[None, None, :]
        y = np.arange(48, dtype=np.float64)[None, :, None]
        cop_x = (stack * x).sum(axis=(1, 2)) / totals
        cop_y = (stack * y).sum(axis=(1, 2)) / totals
        path = np.hypot(np.diff(cop_x), np.diff(cop_y)).sum()
        metrics.extend((
            ReportMetric(f"{stage_id}:total", f"{stage_id} 总相对载荷", float(totals.mean()), "relative_count", "v1-replay-debug/1"),
            ReportMetric(f"{stage_id}:left", f"{stage_id} 左侧相对负重", float((left / totals * 100).mean()), "percent", "v1-replay-debug/1"),
            ReportMetric(f"{stage_id}:path", f"{stage_id} COP 路径", float(path), "sensor_index", "v1-replay-debug/1"),
            ReportMetric(f"{stage_id}:sway", f"{stage_id} ML/AP 摆动范围", float(np.ptp(cop_x) + np.ptp(cop_y)), "sensor_index", "v1-replay-debug/1"),
        ))
        if stage_id == _STAGES[-1]:
            mean = stack.mean(axis=0)
            final_heatmap = tuple(tuple(float(value) for value in row) for row in mean / mean.max())
    return V1DebugResult("DEBUG_READY", tuple(metrics), final_heatmap)


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
            captured_at=now, generated_at=now, protocol_id="static-balance-v1-replay",
            protocol_version="v1-replay-debug/1.0.0", metrics=result.metrics,
            relative_heatmap=result.relative_heatmap,
            summary=REPLAY_DEBUG_SUMMARY,
            disclaimer=REPLAY_DEBUG_DISCLAIMER,
            provenance=tuple(
                value
                for value in (
                    "v1-replay-debug/1",
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
