from __future__ import annotations

from client.reporting.copy import (
    BASIC_REPORT_DISCLAIMER,
    BASIC_REPORT_SUMMARY,
    REPLAY_DEBUG_DISCLAIMER,
    REPLAY_DEBUG_SUMMARY,
    report_badges,
    report_parameter_note,
)


def test_basic_report_copy_describes_available_relative_metrics_without_a_risk_claim() -> None:
    assert "相对压力分布" in BASIC_REPORT_SUMMARY
    assert "不包含稳定性评分" in BASIC_REPORT_SUMMARY
    assert "不作疾病诊断" in BASIC_REPORT_DISCLAIMER
    assert "未来跌倒概率预测" in BASIC_REPORT_DISCLAIMER
    assert report_badges("BASIC") == ("基础分析完成", "不输出风险结论")
    assert "未经批准" in report_parameter_note("BASIC")


def test_replay_copy_keeps_fixture_output_out_of_customer_interpretation() -> None:
    assert "回放" in REPLAY_DEBUG_SUMMARY
    assert "不能代表本次检测结果" in REPLAY_DEBUG_SUMMARY
    assert "不用于诊断" in REPLAY_DEBUG_DISCLAIMER
    assert report_badges("V1_REPLAY_DEBUG") == ("回放调试数据", "不用于诊断")
    assert "不显示风险等级" in report_parameter_note("V1_REPLAY_DEBUG")
