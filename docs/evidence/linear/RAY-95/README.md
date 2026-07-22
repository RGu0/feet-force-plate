# RAY-95 证据：统一报告上游接口边界

- Issue: RAY-95 统一报告：基础版、完整版、PDF 与打印
- URL: https://linear.app/ray-app/issue/RAY-95/统一报告基础版完整版pdf-与打印
- 抓取时间: 2026-07-22
- 当时状态: In Review
- 里程碑/优先级: P4：完整报告 / Urgent

## 本次覆盖的验收快照

本次仅统一完整报告流水线的物理输入约定：云端算法从标准压力信息流重建姿态归一化、COP 和特征，再生成统一 `report_id` 的版本。未覆盖报告持久化、PDF 工件、打印检查或发布门控的完整验收。

## 实现文件与验证

- 规范：`docs/algorithm/physical-input-interface-v1.md`
- 算法总览：`docs/algorithm/v1-static-balance-screening-algorithm.md`
- `git diff --check -- docs/algorithm`: 通过

未完成 PDF/打印人工验证，issue 保持 In Review。

## 关联 commit

`136a5e1` — Unify standard physical pressure input interface
