# RAY-103 Evidence — 自动故障日志、监控告警与支持诊断

- Issue: RAY-103
- URL: https://linear.app/ray-app/issue/RAY-103/自动故障日志监控告警与支持诊断
- 抓取时间: 2026-07-20T08:56:11Z
- 当时状态: Backlog；2026-07-20T09:18:20Z 启动后为 In Progress
- 里程碑: P5：商业运营
- 优先级: High
- 关联 commit SHA: 待本任务提交

## 验收条目快照

- [ ] 结构化事件、崩溃、设备健康、上传状态和错误编号自动上传
- [ ] 日志默认不含姓名/编号明文、token、原始压力载荷或完整报告内容
- [ ] 关联 tenant/terminal/device/session 的内部不可逆或受控标识
- [ ] 采集、分段、上传、云端分析、报告各阶段关键 SLI
- [ ] 错误率、积压、离线终端、摘要冲突和分析失败告警
- [ ] 自动上传持续失败时导出加密诊断包
- [ ] 诊断包默认不含原始会话；附加会话数据需要独立授权动作
- [ ] 支持访问按角色授权并留审计
- [ ] 客户界面只显示通俗状态、错误编号和建议动作

## 实现文件与关键决策

- 实现：`cloud/observability/events.py`、`cloud/observability/alerts.py`、`cloud/observability/uploader.py`、`cloud/observability/diagnostics.py`。
- 数据库：`cloud/observability/migrations/0001_ops.sql`。
- 测试：`tests/cloud/observability/test_events.py`、`test_alerts.py`、`test_uploader.py`、`test_diagnostics.py`、`tests/cloud/test_migrations.py`。
- 已实现严格安全上下文、客户错误动作、SLI/告警规则、窗口/cooldown 去重与恢复、独立遥测队列、失败批次重试、诊断包构建/加密端口和支持访问审计。
- 不自造加密算法；生产诊断包必须通过受控信封加密适配器。
- 支持访问授权和审计建模属于 Task D，运营 UI 不在本任务范围。

## 验证命令与逐项结果

- `python3 -m unittest discover -s tests/cloud/observability -v`
  - RED 1：3 个测试模块因 events/alerts/diagnostics 尚不存在而按预期失败。
  - GREEN 1：13 个安全事件、告警、诊断与支持审计测试通过。
  - RED 2：遥测 uploader 模块缺失而按预期失败。
  - GREEN 2：16 个 observability 测试全部通过。
- `python3 -m unittest tests.cloud.test_migrations -v`
  - RED：3 个 DDL 文件缺失导致 1 failure、3 errors。
  - GREEN：4 个 analysis/reporting/ops 迁移契约测试通过。
- `python3 -m compileall -q cloud/observability tests/cloud/observability tests/cloud/test_migrations.py`
  - 结果：exit 0。
- `git diff --check`
  - 结果：exit 0，无空白错误。
- Task D 最终范围验证：analysis 29、reporting 13、observability 16、migration 4，共 62 个测试通过；根目录默认 discovery 因基线没有根测试发现入口而得到 0 tests，未作为通过证据。

## 自动测试、真机与人工验证边界

- 自动测试计划覆盖隐私字段拒绝、错误事件、关键 SLI、告警去重、恢复、诊断内容白名单和加密调用。
- 实际日志后端、告警通知通道、值班手册演练、崩溃采集和支持权限演练需要集成/人工验证；完成前不应标记 Done。

## 失败或限制

- 当前没有生产日志、告警通知、KMS 或对象存储适配器；测试 encryptor 只验证端口调用与摘要，不是生产加密实现。
- 当前环境无 PostgreSQL 可执行程序，迁移只完成静态契约验证，未在真实数据库执行。
- 崩溃采集、真实断网补传、告警通知、值班 runbook、支持权限和诊断包解密需要集成/人工演练。
- evidence 不保存密钥、个人信息、原始压力载荷或完整客户报告。
