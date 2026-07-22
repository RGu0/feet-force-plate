# RAY-93 证据：标准压力输入与能力门控边界统一

- Issue: RAY-93 静态平衡专业参数能力门控与发布审批
- URL: https://linear.app/ray-app/issue/RAY-93/静态平衡专业参数能力门控与发布审批
- 抓取时间: 2026-07-22
- 当时状态: In Review
- 里程碑/优先级: P4：完整报告 / High

## 本次覆盖的验收快照

本次只覆盖“能力门控的硬件输入边界”一致性：正式输入统一为 `physical-pressure-session/1.0`，包含板面坐标（mm）、法向载荷（N）、实际时间、几何/有效面积声明、质量、测量一致性及版本；COP、速度、RMS、椭圆和阶段比较由算法层计算。未覆盖真机物理输入、参考工件批准、临床验证和全部发布审批验收。

## 实现文件与关键决策

- `docs/algorithm/physical-input-interface-v1.md`
- `docs/algorithm/standard-physical-input-contract.md`
- `docs/algorithm/v1-static-balance-screening-algorithm.md`
- `docs/algorithm/README.md`

硬件层不输出压力特征；加解密、签名、重试和存储由通信/存储层负责。未验证绝对载荷、有效面积、方向或时间语义时保持 `DEGRADED/UNSUPPORTED`。

## 验证

- `git diff --check -- docs/algorithm`: 通过
- `rg` 检查旧 `physical-array-session` 及硬件侧 COP/速度/RMS/风险口径: 未发现旧接口残留

## 边界与限制

以上为文档和 Linear 口径统一证据，不是真机、参考工件或临床验证证据；issue 保持 In Review。

## 关联 commit

`136a5e1` — Unify standard physical pressure input interface
