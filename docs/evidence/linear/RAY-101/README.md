# RAY-101 Evidence

- Issue：`RAY-101` 一键式筛查工作流与页面状态机
- URL：https://linear.app/ray-app/issue/RAY-101/一键式筛查工作流与页面状态机
- 抓取时间：2026-07-20T08:54:41Z
- 当时状态：In Progress
- 里程碑：P2：一键筛查
- 优先级：Urgent

## 验收条目快照

- [ ] P-01 工作台：新检测、网络/设备/待传摘要
- [ ] P-02 受试者识别与快速建档
- [ ] P-03 选填档案
- [ ] P-04 简短授权确认
- [ ] P-05 自动检查：连接、磁盘、标定、联网门槛、零载
- [ ] P-06 站位引导与自动倒计时
- [ ] P-07 检测进行中
- [ ] P-08 处理与基础报告
- [ ] P-09 检测记录
- [ ] P-10 报告预览、PDF 与打印
- [ ] P-11 设备与支持
- [ ] 状态机覆盖准备、采集、分段、上传、分析、报告和失败恢复
- [ ] 非技术操作员无需技术账号即可独立完成标准测试
- [ ] 关键异常提供一个主要恢复动作和稳定错误编号

## 实现与关键决策

实现文件：

- `client/workflow/state_machine.py`：线性流程及 `INCOMPLETE/RETRY_REQUIRED/FAILED` 恢复状态，拒绝跳步。
- `client/workflow/models.py`：不可变 UI DTO；生命周期、有效性、上传、分析和报告状态相互独立。
- `client/workflow/ports.py`：预检、会话、采集、本地分析、报告和遥测端口；没有串口、SQLite 或 HTTP 适配器实现。
- `client/workflow/coordinator.py`：预检阻断、幂等开始/停止、断线收尾、质量门控、基础报告状态和锁定版本的导出/打印编排。
- `client/app/pages.py`：PRD P-01～P-11 页面目录、单主动作和流程步骤映射。
- `client/app/qt_shell.py`：11 页 PySide6 壳层、必要控件、最小 1280x720、16px 正文、48px 动作按钮、可访问名称、导航锁定和通俗错误/非阻断提示。
- `client/app/controller.py`：页面动作、自动预检和采集事件到协调器的绑定。
- `client/tests/test_ray_101_*.py`：状态机、端口编排、页面契约、Qt 壳层和控制器测试。

关键决策：

- RAY-101 只负责页面壳层和编排契约；受试者领域行为、协议配置、指标、实际热力图和基础报告内容分别由 RAY-92/91/90/85/84 接入既有端口。
- 正式会话只在预检通过并开始采集时创建；设备启动失败后形成的会话明确标记 `INCOMPLETE`。
- UI 不接收数据库实体、文件句柄、串口对象或 HTTP 客户端；异常技术详情只交给 `TelemetryPort`。
- 导出与打印始终使用当前查看的 `report_id + version`，后台新版本不能改变当前动作目标。

## 验证

- 自动测试：`QT_QPA_PLATFORM=offscreen /private/tmp/feetforceplate-subtask-b-venv/bin/python -m pytest client/tests/test_ray_101_*.py -q --junitxml=docs/evidence/linear/RAY-101/pytest-results.xml`，结果 `28 passed in 0.17s`。
- 编译检查：`/private/tmp/feetforceplate-subtask-b-venv/bin/python -m compileall -q client/app client/workflow`，退出码 0。
- 边界扫描：对 `client/app`、`client/workflow` 扫描 serial/SQLite/SQLAlchemy/httpx/requests/socket/QSerialPort 直接导入，0 命中。
- 差异检查：`git diff --check` 针对本 issue 文件，退出码 0。
- 自动截图：[`P-01.png`](P-01.png)、[`P-07.png`](P-07.png)、[`P-08.png`](P-08.png)、[`P-10.png`](P-10.png)；由 Qt offscreen 生成，只证明布局可渲染，不等于人工视觉验收。
- JUnit 结果：[`pytest-results.xml`](pytest-results.xml)。
- 真机验证：未执行；未连接 DO-P4864，也未验证真实事件节奏。
- 人工验证：未执行；尚未由非技术操作员走完 11 页，也未完成键盘/屏幕阅读器/目标显示器可用性检查。

## 失败、限制与提交

- 自动化依赖安装在 `/private/tmp/feetforceplate-subtask-b-venv`，未修改仓库同步来的 Windows `.venv`。
- P-02/P-03/P-04 的真实受试者与授权行为待 RAY-92；P-06 待 RAY-91；P-07 实际 48x64/COP 待 RAY-84；P-08/P-10 的真实报告内容与 PDF 工件待 RAY-85。
- 未执行 Windows/macOS 真实字体、A4 打印、1280x720 目标机和高 DPI 人工回归。
- 状态结论：实现和自动验证已完成到 RAY-101 所有权边界，但仍缺人工 UI/操作员及跨 issue 适配器验收，因此只能进入 `In Review`，不能标 `Done`。
- 关联 implementation commit SHA：`9a93b6534f3c9f5d57c4bd0aeacfff45196bd7f4`。

## 2026-07-21 UI 连接补充

- Linear 重新抓取：2026-07-22T02:29:31.738Z；RAY-101 从 `In Review` 退回 `In Progress` 后已回读确认。
- 完成状态回读：2026-07-22T02:53:46.502Z；RAY-101 已确认恢复为 `In Review`。
- 关联 UI issue：RAY-104、RAY-109、RAY-110 均在本轮开始时为 `Backlog`；工作树中已有其未提交视觉实现，本轮不修改、不暂存、不认领这些文件。
- 范围更新：启动设备初始化、5 秒空载传感器校验及其状态机、页面、算法已移交独立任务；本轮未实现或认领 RAY-113、RAY-114、RAY-115。P-05 只保留现有 `PreflightPort` 注入点。

### 新增连接

- `client/app/ui_integration.py` 新增 `LocalReportWorkflowAdapter`：把同一个本地 `ProcessingOutcome` 映射到工作流 `AnalysisPort`、`ReportPort`、版本化 UI 文档读取、PDF 导出和打印交付；同一 session 只处理一次。
- `ReportConnectedController` 在打开 P-10 时按当前工作流的 `report_id + version` 读取精确文档；缺失或版本不一致时停留在安全页面并显示通俗错误。
- 本地 `BASIC` 报告在 UI 标题和来源页脚中明确显示“基础筛查报告/基础版本”，不会被演示 UI 的“完整分析报告”文案误标。
- `build_connected_ui` 是生产组合入口：只接收预检、会话、采集、可靠本地处理、报告交付、打印、遥测和显示刷新端口；不直接访问串口、数据库私表、HTTP 或 License 后台。
- `ConnectedUiRuntime` 保留 controller/coordinator/report adapter，供设备与存储模块通过批准端口注入真实适配器。

### TDD 与验证证据

RED/GREEN 记录：

1. 连接模块缺失：`1 failed` → 建立独立模块后 `1 passed`。
2. 报告适配器和 P-10 呈现缺失：`2 failed, 1 passed` → `3 passed`。
3. UI→工作流→显示帧→本地报告→导出/打印组合根缺失：`1 failed, 3 passed` → `4 passed`。
4. BASIC 报告被误标为完整报告：标题和页脚分别出现预期失败，修复后 `4 passed`。
5. `BASIC_READY` 无版本化文档的不一致状态未拒绝：`1 failed, 4 passed` → `5 passed`。
6. 非有效处理结果仍可携带客户报告：`1 failed, 5 passed` → `6 passed`；现在质量失败文档不会进入 UI 缓存。

最终命令：

```bash
UV_OFFLINE=1 \
UV_CACHE_DIR=/private/tmp/feetforceplate-uv-cache \
FEETFORCEPLATE_VENV=/private/tmp/feetforceplate-subtask-b-venv \
QT_QPA_PLATFORM=offscreen \
./scripts/local-env.sh python -m pytest client/tests -q \
  --junitxml=docs/evidence/linear/RAY-101/pytest-ui-integration-results.xml
```

- 全量结果：`112 passed in 1.75s`。
- 定向连接结果：`6 passed in 0.38s`。
- `./scripts/local-env.sh python -m compileall -q client/app client/workflow client/local_analysis client/reporting client/tests`：通过。
- 连接文件直接导入 serial/SQLite/SQLAlchemy/HTTP/socket/QSerialPort 扫描：0 命中。
- 本轮文件 `git diff --check`：通过。
- JUnit：[`pytest-ui-integration-results.xml`](pytest-ui-integration-results.xml)。

### 自动、真机与人工边界

- 已自动验证：版本钉住、BASIC_READY 不变量、P-07 48×64 显示帧送达、P-10 文档呈现、导出与打印使用同一文档、通用预检端口可组合。
- 未执行：DO-P4864 真机事件、目标 Windows、高 DPI、实体打印、真实设备/存储/同步适配器、非技术操作员完整现场流程。
- 当前全量测试包含工作树中未提交的 RAY-104/109/110 视觉改动；本轮提交不包含这些文件。连接层同时为已提交旧壳层提供 P-10 标签回退，以降低合并顺序耦合。
- 因真机与人工验收仍缺失，本补充完成后 RAY-101 仍只能回到 `In Review`，不能标 `Done`。

### 补充提交

- UI 连接 implementation commit：`b9addb350d4b36b317a68b1e50ee02196b6a4305`
- SHA/evidence 回填 commit：`8079bd4308d8ba20332a9075c4e5d3f950ec0619`
