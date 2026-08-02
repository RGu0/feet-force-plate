# RAY-103 证据：Platform IAM、脱敏运维与敏感访问授权

- Issue: RAY-103 自动故障日志、监控告警与支持诊断
- URL: https://linear.app/ray-app/issue/RAY-103/自动故障日志监控告警与支持诊断
- 抓取时间: 2026-07-22
- 当时状态: In Review
- 里程碑/优先级: P5：商业运营 / High

## 本次覆盖的验收快照

本次仅确认监控和诊断记录引用标准输入/算法版本，而不把原始力帧或硬件预计算特征写入客户边界。未覆盖告警演练、诊断包生成和目标监控环境验收。

## 实现文件与验证

- 接口规范：`docs/algorithm/physical-input-interface-v1.md`
- `git diff --check -- docs/algorithm`: 通过

告警演练和诊断包验收未完成，issue 保持 In Review。

## 关联 commit

`136a5e1` — Unify standard physical pressure input interface

## 2026-08-01 Platform IAM refresh

当前实现具有多个独立 Platform identity，以及 `PLATFORM_OWNER`、
`PLATFORM_OPERATIONS`、`PLATFORM_SUPPORT`、`PLATFORM_ENGINEER` 四种可扩展角色。
跨机构列表仅返回脱敏统计；身份披露要求 support/owner 获得最长 15 分钟的
`SensitiveAccessGrant`，签发和使用均写入审计。

`platform-iam-summary.json` 与 `cloud/tests/test_platform_iam.py`、
`cloud/tests/test_platform_api.py` 是 `PROVEN_LOCAL` 证据。真实 PostgreSQL
持久化仍为 `PENDING_POSTGRES`，正式 SSO/MFA 属于商业扩展，不把它们伪装成
当前已完成项。
