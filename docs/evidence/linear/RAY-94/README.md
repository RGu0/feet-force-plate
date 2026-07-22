# RAY-94 证据：报告输入边界统一

- Issue: RAY-94 报告内静态平衡参数与物理曲线呈现
- URL: https://linear.app/ray-app/issue/RAY-94/报告内静态平衡参数与物理曲线呈现
- 抓取时间: 2026-07-22
- 当时状态: In Review
- 里程碑/优先级: P4：完整报告 / Medium

## 本次覆盖的验收快照

本次仅确认报告上游输入口径：报告消费算法层结果；硬件层唯一标准输出为 `physical-pressure-session/1.0`，不直接提供 COP、速度或其他压力特征。未覆盖四阶段曲线渲染、隐私白名单、PDF/打印人工检查。

## 实现文件

详见 `docs/algorithm/physical-input-interface-v1.md` 及 `docs/algorithm/v1-static-balance-screening-algorithm.md`。

## 验证与限制

- `git diff --check -- docs/algorithm`: 通过
- 未执行 PDF/打印人工验收，issue 保持 In Review。

## 关联 commit

`136a5e1` — Unify standard physical pressure input interface
