# RAY-85 Evidence

- Issue：`RAY-85` 本地基础分析与断网基础报告
- URL：https://linear.app/ray-app/issue/RAY-85/本地基础分析与断网基础报告
- 初次抓取时间：2026-07-20T08:54:41Z
- 开始实现时间：2026-07-20T10:20:16Z
- 初次抓取状态：Backlog
- 当前工作流状态：In Progress（实现与自动验证完成后将转 In Review）
- 里程碑：P2：一键筛查
- 优先级：High
- 关系：related issue `RAY-91`；无阻塞/被阻塞关系

## 验收条目快照

- [x] 只从 `ReliableSessionSourcePort` 读取可靠落盘原始数据，不依赖上传成功
- [x] 生成热力图、基础相对压力分布和左右负重；COP 由 RAY-90 计算但未验证前不映射到客户报告
- [x] 指标沿用 RAY-90 的采样率、标定、时长、协议、验证状态和质量门控
- [x] 输出/持久化版本化、不可变 `LocalAnalysisResult`
- [x] 有效会话生成 `BASIC_READY`；质量失败只持久化结果并要求重测，不生成报告
- [x] 本地结果可形成上传快照，显式标记非权威且要求云端从原始数据重建
- [x] 编排器没有网络/同步依赖；进程内和重启后均幂等复用不可变结果
- [x] 复用 RAY-90 固定 fixture 与独立同定义容差对齐测试

## 实现文件与关键决策

- `client/local_analysis/service.py`：可靠会话只读端口、本地分析结果存储端口、基础报告存储端口、离线处理编排、幂等复用和非权威上传快照。
- `client/reporting/models.py`：不可变 `BasicReportDocument`、版本/状态/类型、白名单指标、相对热力图、筛查免责声明和 provenance；确定性 JSON 序列化。
- `client/tests/test_ray_85_service.py`：可靠落盘、有效/无效质量、断网独立、不可变幂等、进程重启复用、上传权威边界。
- `client/tests/test_ray_85_reporting.py`：BASIC_READY 文档序列化、无诊断声明、无内部质量/堆栈字段。
- [sample-basic-report-summary.json](sample-basic-report-summary.json)：固定合成 fixture 的脱敏摘要，完整 48×64 热力图因冗长不在 evidence 摘要重复。

关键决策：processor 构造函数仅接受本地 source/store/report port 和时钟，没有上传、同步、HTTP 或云端端口；`StoredLocalAnalysis.authority=LOCAL_SUPPORTING`，上传快照固定 `SUPPORTING_NON_AUTHORITATIVE` 且 `cloud_recompute_from_raw=true`；报告 mapper 只接受 RAY-90 的 `customer_metrics`，不允许内部 COP、质量原因、频域或参考范围进入客户文档；同一 session 由报告存储端口保留 `report_id` 与下一个不可变版本。

## 验证命令与结果

执行时间：2026-07-20T10:23:59Z。

```bash
QT_QPA_PLATFORM=offscreen /private/tmp/feetforceplate-subtask-b-venv/bin/python \
  -m pytest client/tests -q \
  --junitxml=docs/evidence/linear/RAY-85/pytest-results.xml
```

结果：`73 passed`；包含 RAY-85 自动测试以及 RAY-101/RAY-92/RAY-91/RAY-90 回归。

```bash
/private/tmp/feetforceplate-subtask-b-venv/bin/python -m compileall -q \
  client/app client/workflow client/local_analysis client/reporting client/tests
```

结果：通过。

```bash
! rg -n "^(import|from) (serial|sqlite3|requests|httpx|urllib|aiohttp)" \
  client/app client/workflow client/local_analysis client/reporting
```

结果：0 命中。

## 自动测试、真机与人工边界

- 已自动验证：可靠存储标记为 false 时在分析前拒绝；VALID 生成 `report-1/version 1/BASIC_READY`；INVALID 持久化结果但无报告；指标白名单仅三项相对数值；同一处理器重复调用不重读；新处理器通过 store 复用时不重读；上传快照显式非权威；JSON 无内部 quality/stack；全客户端回归。
- 尚未验证：其他任务提供的真实加密分段/会话存储适配器；崩溃恢复过程；大量真实会话的性能/内存峰值；真实断网/慢网/云端故障注入；同步模块上传本地快照；云端生产从原始数据重算与报告升级；COP 客户指标验证。
- 因真实适配器、故障注入、性能和云端双跑均未完成，本 issue 只能进入 `In Review`，不得标 `Done`。

## 失败或限制

- 当前 source fixture 在内存中模拟“已可靠落盘”，不会声称替代真实加密分段/校验/恢复验证。
- `sample-basic-report-summary.json` 为 evidence 摘要，不是完整导出的交付 PDF；PDF/打印由后续 reporting/packaging 工作继续验证。
- BASIC_READY 只包含非诊断性相对指标；缺少真实验证的 COP 不会因产品文案要求而绕过 RAY-90 门控。

## 关联提交

- 实现与本 evidence：待提交后回填完整 commit SHA。
