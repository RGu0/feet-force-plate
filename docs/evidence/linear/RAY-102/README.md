# RAY-102 Evidence — 云端分析流水线与版本化重算

- Issue: RAY-102
- URL: https://linear.app/ray-app/issue/RAY-102/云端分析流水线与版本化重算
- 抓取时间: 2026-07-20T08:56:11Z
- 当时状态: Backlog；2026-07-20T09:03:21Z 启动后为 In Progress
- 里程碑: P4：完整报告
- 优先级: Urgent
- 当前状态: In Review
- 关联实现 commit SHA: `7b8ebb0ba90fbda6b062ffd845528986c37c2c73`

## 验收条目快照

- [ ] INGESTED_COMPLETE 事件触发，最终清单未确认时不发布结果
- [ ] 解密/解码 → 质量评估 → 预处理 → 一级特征 → 指标/模型 → 报告数据
- [ ] 一级特征在服务端从原始数据重建
- [ ] 数据、协议、标定、特征、算法、模型和报告模式全部版本化
- [ ] 任务幂等，同一输入与版本不重复产生冲突结果
- [ ] 算法升级重算生成新版本，不覆盖既有交付
- [ ] 指标能力门控和发布审批
- [ ] 可追溯到 session manifest 与原始分段摘要
- [ ] 失败原因进入内部状态与日志，不进入客户报告
- [ ] 性能与队列扩缩容不改变结果一致性

## 实现文件与关键决策

- 实现：`cloud/analysis/models.py`、`cloud/analysis/features.py`、`cloud/analysis/gates.py`、`cloud/analysis/ports.py`、`cloud/analysis/orchestrator.py`。
- 数据库：`cloud/analysis/migrations/0001_analysis.sql`。
- 测试：`tests/cloud/analysis/test_orchestrator.py`，并回归全部 `tests/cloud/analysis`。
- 已实现 `cloud/analysis` 事件入口、版本化运行键、重算、内部失败状态、质量评估端口、原始会话加载端口和事件发布端口。
- 只消费仓库批准的 `session.ingested.v1`；Linear 的 `INGESTED_COMPLETE` 是同一已验证 manifest 门槛的业务名称。
- 不修改 `cloud/ingestion`、接收 API 或原始分段协议。

## 验证命令与逐项结果

- `python3 -m unittest tests.cloud.analysis.test_orchestrator -v`
  - RED：因 `AnalysisRunStatus`/编排模型尚不存在而按预期失败。
  - GREEN：8 个编排测试全部通过。
- `python3 -m unittest discover -s tests/cloud/analysis -v`
  - 回归：29 个 analysis 测试全部通过，0 failure，0 error。
- `python3 -m compileall -q cloud/analysis tests/cloud/analysis`
  - 结果：exit 0。
- `git diff --check`
  - 结果：exit 0，无空白错误。
- `python3 -m unittest tests.cloud.test_migrations -v`
  - 结果：4 个 Task D 迁移契约测试通过；当前环境没有 PostgreSQL，未执行真实迁移。
- Task D 最终范围验证：analysis 29、reporting 13、observability 16、migration 4，共 62 个测试通过；根目录默认 discovery 因基线没有根测试发现入口而得到 0 tests，未作为通过证据。

## 自动测试、真机与人工验证边界

- 自动测试计划覆盖事件门槛、幂等运行键、版本化重算、确定性、失败日志和身份隔离。
- PostgreSQL、对象存储、队列扩缩容、分段解密密钥和真实性能容量需要集成环境验证；完成前不应标记 Done。

## 失败或限制

- 当前基线没有 ingestion 代码、真实对象存储或队列适配器；Task D 提供显式端口与线程安全参考内存适配器。
- 真实分段解密/解码、PostgreSQL 事务、S3 对象读取、至少一次队列重复投递与峰值扩缩容仍需集成环境验证。
