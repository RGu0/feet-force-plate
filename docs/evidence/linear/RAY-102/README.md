# RAY-102 证据：云端标准压力输入统一

- Issue: RAY-102 云端分析流水线与版本化重算
- URL: https://linear.app/ray-app/issue/RAY-102/云端分析流水线与版本化重算
- 抓取时间: 2026-07-22
- 当时状态: In Progress
- 里程碑/优先级: P4：完整报告 / Urgent

## 本次覆盖的验收快照

已将 Linear 描述和本地规范统一为：RAY-102 消费 RAY-117 的唯一标准流 `physical-pressure-session/1.0`（板面坐标、法向载荷 N、实际时间、质量和版本）；姿态归一化、COP、速度、RMS、范围、椭圆和阶段差异全部由云端算法层计算。旧的硬件 `physical-array-session` 二次输入假设已移除。

本次未覆盖代码适配、完整会话触发、AnalysisRun 持久化、版本化重算和真机/目标环境验收。

## 实现文件与验证

- `docs/algorithm/physical-input-interface-v1.md`
- `docs/algorithm/standard-physical-input-contract.md`
- `docs/algorithm/v1-static-balance-screening-algorithm.md`
- `git diff --check -- docs/algorithm`: 通过
- `rg` 检查旧接口口径: 通过

## 关联 commit

`136a5e1` — Unify standard physical pressure input interface
