from __future__ import annotations

from datetime import UTC, datetime

from cloud.analysis.models import AnalysisRun, AnalysisRunStatus, ValidationStatus
from cloud.reporting.models import (
    PublicFigure,
    PublicMetric,
    PublicSeries,
    ReportContext,
    ReportDocument,
    ReportKind,
)


_CORE_METRIC_IDS = {
    "relative_total_load",
    "left_right_load_balance",
    "anterior_posterior_load_balance",
}


class CloudReportBuilder:
    def build(
        self,
        *,
        run: AnalysisRun,
        context: ReportContext,
        report_id: str,
        version_number: int,
    ) -> ReportDocument:
        if run.status is not AnalysisRunStatus.SUCCEEDED or run.feature_set is None:
            raise ValueError("only successful persisted analysis can build a report")

        approved = tuple(
            PublicMetric(
                metric_id=result.metric_id,
                definition=result.definition,
                value=result.value_numeric,
                unit=result.unit,
            )
            for result in run.metric_results
            if result.validation_status is ValidationStatus.APPROVED
        )
        if not approved:
            raise ValueError("no approved supported metrics are available for reporting")

        algorithm_versions = ",".join(
            sorted(
                {
                    f"{result.algorithm_id}@{result.algorithm_version}"
                    for result in run.metric_results
                    if result.validation_status is ValidationStatus.APPROVED
                }
            )
        )
        core_metrics = tuple(metric for metric in approved if metric.metric_id in _CORE_METRIC_IDS)
        professional_metrics = tuple(
            metric for metric in approved if metric.metric_id not in _CORE_METRIC_IDS
        )
        approved_ids = {metric.metric_id for metric in approved}
        figures = _build_figures(run.feature_set, approved_ids)

        return ReportDocument(
            report_id=report_id,
            version_number=version_number,
            kind=ReportKind.CLOUD_COMPLETE,
            generated_at=datetime.now(UTC),
            context=context,
            screening_summary=("本次健康筛查已完成云端分析。",),
            risk_prompts=(
                "结果用于健康筛查与风险提示；如有持续不适或关注项，建议进一步评估。",
            ),
            core_metrics=core_metrics,
            professional_metrics=professional_metrics,
            professional_figures=figures,
            plain_language_guidance=(
                "请结合实际情况阅读本报告；本报告不作疾病诊断或治疗建议。",
            ),
            provenance=(
                ("report_schema_version", run.report_schema_version),
                ("feature_pipeline_version", run.key.pipeline_version),
                ("algorithm_set_version", run.key.algorithm_set_version),
                ("model_set_version", run.key.model_set_version),
                ("metric_algorithms", algorithm_versions),
            ),
        )


def _build_figures(feature_set, approved_metric_ids: set[str]) -> tuple[PublicFigure, ...]:
    sample_rate = feature_set.actual_sample_rate_hz
    statement = (
        f"采集约 {sample_rate:.1f} Hz；显示或连线仅用于阅读，不代表更高采样率。"
    )
    time_points = tuple(
        index / sample_rate if sample_rate > 0 else float(index)
        for index in range(len(feature_set.total_load_by_frame))
    )
    figures: list[PublicFigure] = []

    if "relative_total_load" in approved_metric_ids:
        if len(feature_set.mean_sensor_load) == 48 * 64:
            figures.append(
                PublicFigure(
                    figure_id="relative_load_heatmap",
                    title="平均相对载荷热力图",
                    figure_type="heatmap",
                    source_sample_rate_hz=sample_rate,
                    source_sampling_statement=statement,
                    print_style="grayscale_scale",
                    alt_text="48×64 传感点平均相对载荷分布，深浅同时由数值色标说明。",
                    series=(),
                    matrix_shape=(48, 64),
                    matrix_values=feature_set.mean_sensor_load,
                )
            )
        figures.append(
            PublicFigure(
                figure_id="total_load_curve",
                title="相对总载荷-时间曲线",
                figure_type="line",
                source_sample_rate_hz=sample_rate,
                source_sampling_statement=statement,
                print_style="line_and_marker",
                alt_text="随采集时间变化的相对总载荷曲线。",
                series=(
                    PublicSeries(
                        name="相对总载荷",
                        unit="relative_count",
                        points=tuple(zip(time_points, feature_set.total_load_by_frame, strict=True)),
                        line_style="solid",
                        marker="circle",
                    ),
                ),
            )
        )

    if "left_right_load_balance" in approved_metric_ids:
        figures.append(
            PublicFigure(
                figure_id="left_right_load_curve",
                title="左右区域相对载荷曲线",
                figure_type="line-comparison",
                source_sample_rate_hz=sample_rate,
                source_sampling_statement=statement,
                print_style="line_and_marker",
                alt_text="左侧使用实线圆点，右侧使用虚线方点，支持灰阶区分。",
                series=(
                    PublicSeries(
                        name="左侧",
                        unit="relative_count",
                        points=tuple(zip(time_points, feature_set.left_load_by_frame, strict=True)),
                        line_style="solid",
                        marker="circle",
                    ),
                    PublicSeries(
                        name="右侧",
                        unit="relative_count",
                        points=tuple(zip(time_points, feature_set.right_load_by_frame, strict=True)),
                        line_style="dashed",
                        marker="square",
                    ),
                ),
            )
        )

    if "anterior_posterior_load_balance" in approved_metric_ids:
        figures.append(
            PublicFigure(
                figure_id="anterior_posterior_load_curve",
                title="前后区域相对载荷曲线",
                figure_type="line-comparison",
                source_sample_rate_hz=sample_rate,
                source_sampling_statement=statement,
                print_style="line_and_marker",
                alt_text="前部使用实线三角标记，后部使用点线菱形标记。",
                series=(
                    PublicSeries(
                        name="前部",
                        unit="relative_count",
                        points=tuple(zip(time_points, feature_set.anterior_load_by_frame, strict=True)),
                        line_style="solid",
                        marker="triangle",
                    ),
                    PublicSeries(
                        name="后部",
                        unit="relative_count",
                        points=tuple(zip(time_points, feature_set.posterior_load_by_frame, strict=True)),
                        line_style="dotted",
                        marker="diamond",
                    ),
                ),
            )
        )

    if "cop_path_length" in approved_metric_ids:
        cop_points = tuple(
            (x, y)
            for x, y in feature_set.cop_xy_by_frame
            if x is not None and y is not None
        )
        figures.append(
            PublicFigure(
                figure_id="cop_trajectory",
                title="压力中心（COP）轨迹",
                figure_type="xy-trajectory",
                source_sample_rate_hz=sample_rate,
                source_sampling_statement=statement,
                print_style="line_and_marker",
                alt_text="压力中心在 48×64 传感点坐标系中的轨迹，按采集顺序连线。",
                series=(
                    PublicSeries(
                        name="COP",
                        unit="sensor_cell",
                        points=cop_points,
                        line_style="solid",
                        marker="circle",
                    ),
                ),
            )
        )

    return tuple(figures)
