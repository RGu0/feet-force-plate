from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from cloud.analysis.features import SessionFeatureSet, StageFeatureSet
from cloud.analysis.physical_input import StageId
from cloud.analysis.risk_rules import RiskTier, ScreeningRiskResult
from cloud.reporting.models import (
    PublicFigure,
    PublicMetric,
    PublicSeries,
    ReportArtifact,
    ReportContext,
    ReportDocument,
    ReportKind,
    ReportPublishedEvent,
    ReportVersion,
)
from cloud.reporting.pdf import MinimalPdfRenderer
from cloud.reporting.service import (
    InMemoryArtifactStore,
    InMemoryReportEventPublisher,
    InMemoryReportRepository,
)


_RISK_LABELS = {
    RiskTier.LOW: "低风险提示",
    RiskTier.MEDIUM: "中风险提示",
    RiskTier.HIGH: "高风险提示",
    RiskTier.INSUFFICIENT_DATA: "暂不能形成完整风险分级",
    RiskTier.TECHNICAL_INVALID: "本次数据无法用于风险分级",
}


class StaticBalanceReportBuilder:
    """Build the customer-safe V1 static balance report document."""

    def build(
        self,
        *,
        risk: ScreeningRiskResult,
        features: SessionFeatureSet,
        context: ReportContext,
        report_id: str,
        version_number: int,
        report_schema_version: str,
        rule_set_version: str,
    ) -> ReportDocument:
        core_metrics = (
            PublicMetric(
                metric_id="balance_index",
                definition="V1 静态平衡综合筛查指数（0–100）",
                value=float(risk.balance_index),
                unit="score",
            ),
        )
        professional_metrics = _professional_metrics(features)
        figures = _professional_figures(features)
        risk_label = _RISK_LABELS[risk.risk_tier]
        guidance = (
            "本报告用于机构健康筛查和风险提示，不作疾病诊断。",
            "如提示高风险，建议在安全陪同下进一步咨询医疗或专业机构。"
            if risk.risk_tier is RiskTier.HIGH
            else "如有持续不适、近期变化或本人担忧，建议进一步咨询专业人员。",
        )
        return ReportDocument(
            report_id=report_id,
            version_number=version_number,
            kind=ReportKind.CLOUD_COMPLETE,
            generated_at=datetime.now(UTC),
            context=context,
            screening_summary=(
                f"静态平衡综合筛查指数：{risk.balance_index}/100",
                f"筛查提示：{risk_label}",
                *tuple(
                    f"{stage.stage_id.value} 实际完成时长：{stage.completion_time_s:.1f} 秒"
                    for stage in features.stages
                ),
            ),
            risk_prompts=(
                "综合提示由背景信息、动作完成情况和物理平衡指标按规则合并。",
            ),
            core_metrics=core_metrics,
            professional_metrics=professional_metrics,
            professional_figures=figures,
            plain_language_guidance=guidance,
            provenance=(
                ("report_schema_version", report_schema_version),
                ("rule_set_version", rule_set_version),
                ("feature_pipeline_version", features.pipeline_version),
            ),
        )


def _professional_metrics(features: SessionFeatureSet) -> tuple[PublicMetric, ...]:
    metrics: list[PublicMetric] = []
    for stage in features.stages:
        prefix = stage.stage_id.value.lower()
        metrics.extend(
            (
                PublicMetric(
                    metric_id=f"{prefix}_cop_path_mm",
                    definition=f"{stage.stage_id.value} 压力中心累计路径",
                    value=stage.cop_path_mm,
                    unit="mm",
                ),
                PublicMetric(
                    metric_id=f"{prefix}_mean_velocity_mm_s",
                    definition=f"{stage.stage_id.value} 压力中心平均速度",
                    value=stage.mean_velocity_mm_s,
                    unit="mm/s",
                ),
                PublicMetric(
                    metric_id=f"{prefix}_ellipse_area_95_mm2",
                    definition=f"{stage.stage_id.value} 压力中心 95% 椭圆面积",
                    value=stage.ellipse_area_95_mm2,
                    unit="mm²",
                ),
            )
        )
    metrics.extend(
        (
            PublicMetric(
                metric_id="eyes_closed_ellipse_ratio",
                definition="闭眼/睁眼压力中心 95% 椭圆面积比",
                value=features.eyes_closed_ratio("ellipse_area_95_mm2"),
                unit="ratio",
            ),
            PublicMetric(
                metric_id="front_foot_ellipse_difference",
                definition="左右脚在前压力中心 95% 椭圆面积相对差异",
                value=features.side_difference("ellipse_area_95_mm2"),
                unit="ratio",
            ),
        )
    )
    return tuple(metrics)


def _sample_rate(stage: StageFeatureSet) -> float:
    if len(stage.timestamps_s) < 2:
        return 0.0
    deltas = [right - left for left, right in zip(stage.timestamps_s, stage.timestamps_s[1:])]
    nominal = sorted(deltas)[len(deltas) // 2]
    return 1.0 / nominal if nominal > 0 else 0.0


def _professional_figures(features: SessionFeatureSet) -> tuple[PublicFigure, ...]:
    figures: list[PublicFigure] = []
    for stage in features.stages:
        rate = _sample_rate(stage)
        relative_time = stage.timestamps_s[0] if stage.timestamps_s else 0.0
        points = tuple(
            (timestamp - relative_time, value)
            for timestamp, value in zip(stage.timestamps_s, stage.cop_ml_mm, strict=True)
        )
        ap_points = tuple(
            (timestamp - relative_time, value)
            for timestamp, value in zip(stage.timestamps_s, stage.cop_ap_mm, strict=True)
        )
        figures.append(
            PublicFigure(
                figure_id=f"{stage.stage_id.value.lower()}_cop_curve",
                title=f"{stage.stage_id.value} 压力中心曲线",
                figure_type="ml-ap-time",
                source_sample_rate_hz=rate,
                source_sampling_statement=(
                    f"由物理输入时间戳估计约 {rate:.1f} Hz；曲线用于阅读，不代表更高采样率。"
                ),
                print_style="line_and_marker",
                alt_text="压力中心 ML 与 AP 方向随阶段时间变化的曲线。",
                series=(
                    PublicSeries(
                        name="ML",
                        unit="mm",
                        points=points,
                        line_style="solid",
                        marker="circle",
                    ),
                    PublicSeries(
                        name="AP",
                        unit="mm",
                        points=ap_points,
                        line_style="dashed",
                        marker="square",
                    ),
                ),
            )
        )
    return tuple(figures)


class StaticBalanceCloudReportService:
    def __init__(
        self,
        *,
        repository: InMemoryReportRepository,
        artifact_store: InMemoryArtifactStore,
        builder: StaticBalanceReportBuilder,
        renderer: MinimalPdfRenderer,
        publisher: InMemoryReportEventPublisher,
    ) -> None:
        self.repository = repository
        self.artifact_store = artifact_store
        self.builder = builder
        self.renderer = renderer
        self.publisher = publisher

    def publish(
        self,
        *,
        tenant_id: str,
        session_id: str,
        source_analysis_run_id: str,
        correlation_id: str,
        report_schema_version: str,
        rule_set_version: str,
        risk: ScreeningRiskResult,
        features: SessionFeatureSet,
        context: ReportContext,
    ) -> ReportVersion:
        if features.session_id != session_id:
            raise ValueError("feature session identity does not match report session")

        def build(report_id: str, version_number: int) -> ReportVersion:
            document = self.builder.build(
                risk=risk,
                features=features,
                context=context,
                report_id=report_id,
                version_number=version_number,
                report_schema_version=report_schema_version,
                rule_set_version=rule_set_version,
            )
            public_json = json.dumps(
                document.to_public_dict(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            document_sha256 = hashlib.sha256(public_json).hexdigest()
            pdf = self.renderer.render(document)
            artifact_sha256 = hashlib.sha256(pdf).hexdigest()
            object_key = (
                f"tenants/{tenant_id}/reports/{report_id}/"
                f"v{version_number}/{artifact_sha256}.pdf"
            )
            self.artifact_store.put(object_key, pdf, artifact_sha256)
            return ReportVersion(
                report_id=report_id,
                tenant_id=tenant_id,
                session_id=session_id,
                version_number=version_number,
                kind=ReportKind.CLOUD_COMPLETE,
                source_analysis_run_id=source_analysis_run_id,
                report_schema_version=report_schema_version,
                document=document,
                document_sha256=document_sha256,
                artifact=ReportArtifact(
                    object_key=object_key,
                    content_type="application/pdf",
                    size_bytes=len(pdf),
                    sha256=artifact_sha256,
                    renderer_version=self.renderer.renderer_version,
                    template_version=self.renderer.template_version,
                ),
                generated_at=document.generated_at,
            )

        version, created = self.repository.append_cloud_version(
            tenant_id=tenant_id,
            session_id=session_id,
            source_analysis_run_id=source_analysis_run_id,
            build=build,
        )
        if created:
            self.publisher.publish(
                ReportPublishedEvent(
                    event_type="report.published.v1",
                    tenant_id=tenant_id,
                    report_id=version.report_id,
                    correlation_id=correlation_id,
                    version_number=version.version_number,
                    kind=ReportKind.CLOUD_COMPLETE,
                )
            )
        return version
