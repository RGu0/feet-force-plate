"""Approved customer-facing copy for local and replay report states.

The local path has not completed clinical validation.  Keep its language
descriptive: it may say what data was processed, but never infer a diagnosis,
risk level, reference range, or a future fall probability.
"""

from __future__ import annotations


BASIC_REPORT_SUMMARY = (
    "本次已完成基础相对压力分布分析。当前报告展示总相对载荷与左右相对"
    "负重，便于复核本次站立时的受力分布；不包含稳定性评分、疾病判断或"
    "跌倒风险预测。"
)

BASIC_REPORT_DISCLAIMER = (
    "本报告用于健康筛查和专业分析参考，不作疾病诊断、治疗建议或未来跌倒"
    "概率预测。当前基础分析仅呈现已批准的相对指标；是否需要进一步评估，"
    "应由专业人员结合访谈和实际情况判断。"
)

PHYSICAL_RELATIVE_REPORT_SUMMARY = (
    "本次已完成四段静态动作的基础分析。报告按阶段展示平均相对压力分布、"
    "前后左右相对负载以及 COP 的路径、速度和 ML/AP 方向描述性参数；这些"
    "指标不用于稳定性分级、疾病判断或跌倒风险预测。"
)

REPLAY_DEBUG_SUMMARY = (
    "已完成四段固定夹具回放。页面和基础特征仅用于验证本地工作流与显示"
    "链路；受试者、时间、指标和热图均为去标识化回放调试数据，不能代表"
    "本次检测结果。"
)

REPLAY_DEBUG_DISCLAIMER = (
    "回放调试报告不代表本次受试者真实测量，不用于诊断、风险判断、临床"
    "参考范围比较或治疗建议。"
)


def report_badges(kind: str) -> tuple[str, str]:
    """Return the two short, non-diagnostic badges for the report preview."""
    if kind == "V1_REPLAY_DEBUG":
        return ("回放调试数据", "不用于诊断")
    if kind.upper() == "BASIC":
        return ("基础分析完成", "不输出风险结论")
    return ("完整分析结果", "请结合专业判断")


def report_parameter_note(kind: str) -> str:
    """Describe exactly what the selected report type does not claim."""
    if kind == "V1_REPLAY_DEBUG":
        return "本页仅呈现回放夹具的调试特征；不显示风险等级、综合评分或临床参考范围。"
    if kind.upper() == "BASIC":
        return "基础报告展示四段平均相对压力分布与描述性 COP 参数；不提供未经批准的参考范围、稳定性分级、疾病判断或跌倒风险预测。"
    return "专业参数应标明算法、协议和参考范围版本，并由具备相应资质的人员结合实际情况解读。"
