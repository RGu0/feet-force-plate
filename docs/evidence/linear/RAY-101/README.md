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

## 2026-07-21 P-02 现场版式反馈修正

- 触发：人工查看开发演示时发现“已找到唯一档案”详情横向挤压“确认并继续”主操作；原型也以年龄段显示，不符合具体年龄的展示要求。
- 实现：`client/app/qt_shell.py` 让匹配详情与核对提示自动换行，主操作固定为至少 200×56 px，并留出 24 px 内容间距；示例档案改为“年龄 64 岁”。`client/app/demo.py` 的查找反馈同步使用具体年龄和性别。
- 自动验证：`QT_QPA_PLATFORM=offscreen ./scripts/local-env.sh python -m pytest client/tests/test_ray_101_qt_shell.py client/tests/test_ui_demo.py -q --junitxml=docs/evidence/linear/RAY-101/pytest-ui-layout-results.xml`，结果 `9 passed in 0.72s`。新增断言验证 1280 px 窗口下详情与主操作不重叠、主操作宽度不少于 200 px、年龄文案为具体值。
- 人工/真机边界：修正已由 offscreen 自动布局检查覆盖；尚待在目标 Windows 显示器、高 DPI 和实体打印流程中人工确认。未连接 DO-P4864，不涉及设备初始化或 5 秒空载校验。

## 2026-07-26 发布阻断复核

- 映射：正式默认入口不再自动进入本地 fixture 回放；`main.py` 默认启动 package 的强制设备启动校验，只有显式 `--replay` 才进入回放，`--demo` 仍是显式设计演示。
- 实现：`main.py`；`tests/test_main_entry.py`。回放路径通过 `ProtocolCatalog` 的明确 replay-debug 开关选择试点协议。
- 验证：`QT_QPA_PLATFORM=offscreen ./scripts/local-env.sh python -m pytest -q`，**336 passed in 28.03s**；针对入口、启动、协议和本地索引的组合集 **112 passed in 1.00s**。
- 限制：`client/app/packaged_entry.py` 的默认工作台仍未具备正式采集、会话存储和报告适配器的完整组合根；仓库中现有完整组合仅是明确的 `REPLAY_DEBUG` 路径，不能安全复用于机构入口。不得把这一缺口以 `ScreeningWindow()` 或 fixture 回放掩盖。RAY-101 保持 In Review。
- Commit SHA：尚未创建；工作树已有用户未提交改动，本轮未暂存。

## 2026-07-31 正式入口组合与四阶段全页面证据

### P-00 到强制启动门禁的生产组合边界

- `client/app/packaged_entry.py` 新增 `AuthenticatedInstitutionSession`、`InstitutionAuthenticationPort` 与 `InstitutionApplication`。生产认证只返回机构、站点、终端和账号标识，不在应用组合根持有密码。
- 只有生产认证成功后才构造并启动 `StartupGatePort`；认证拒绝、认证服务异常或门禁启动异常都停留在 P-00，并只向操作员显示通俗错误，不回显适配器异常详情。
- `client/app/institution_access.py` 增加正式入口隔离开关。原有本机测试 License 仍可完成本机注册/登录演示，但正式组合根明确禁止把本机测试凭据交给生产认证回调，因此不能获得生产启动权限。
- `main()` 现在持有 `InstitutionApplication` 生命周期；默认包未注入真实 License 适配器时仍安全停留在 P-00，不伪造登录成功，也不退回裸 `ScreeningWindow()`。

TDD 记录：

1. RED：新测试因缺少 `AuthenticatedInstitutionSession` 无法收集，`1 error`。
2. GREEN：生产认证成功、认证拒绝、本机 License 隔离、门禁启动失败四条组合行为，与既有 P-00/启动门禁相邻测试合计 `13 passed in 0.63s`。
3. JUnit：[`pytest-packaged-composition-20260731.xml`](pytest-packaged-composition-20260731.xml)。

### 去标识真实采集四阶段的 P-01～P-11 本机证据

- 输入：已批准的去标识 DO-P4864 四阶段工程回放 fixture，SHA-256 `2495b910bbf7e4fcca0cd0db36dde809f0fd6395bb6060eded44db575acd6f90`，共 1,658 帧；证据摘要不包含原始矩阵。
- 执行：`QT_QPA_PLATFORM=offscreen ./scripts/local-env.sh python main.py --replay --verify --output-dir docs/evidence/linear/RAY-101/local-four-stage-workflow-20260731 --replay-speed 500`。
- 结果：`status=PASSED`，实际访问 `P-01`～`P-11` 全部 11 页；四阶段分别为睁眼双足、闭眼双足、左脚在前半串联、右脚在前半串联；生成 14 张页面截图、版本固定的调试报告 PDF、加密受试者导出审计和 `summary.json`。
- 工件目录：[`local-four-stage-workflow-20260731/`](local-four-stage-workflow-20260731/)；机器可读摘要：[`summary.json`](local-four-stage-workflow-20260731/summary.json)；报告：[`report.pdf`](local-four-stage-workflow-20260731/report.pdf)。
- 验证器 TDD：先因缺少 `visited_page_ids` 失败，再扩展为每页抓取与完整页面集合断言；最终 `client/tests/test_local_mvp_validation.py` 为 `2 passed in 13.92s`。

### 结论与边界

- 现在可以用一组本机可重复证据证明 11 页均可渲染并由一条四阶段工作流实际到达；P-07 使用真实采集 fixture，P-10 生成真实本地 PDF，P-09 可从本地记录重新打开同一报告版本。
- 该工件明确为 `V1_REPLAY_DEBUG` / `DEBUG_READY`，只证明本地软件工作流、显示、存储与报告链路；不证明实时硬件、生产 License、生产云端、物理打印、临床有效性或操作员可用性。
- 正式包仍缺真实远端认证适配器和正式设备/存储/同步工作台端口注入；非技术操作员尚未在目标 Windows 与实体硬件上独立完成流程。因此 RAY-101 仍应保持 `In Review`，不能标 `Done`。

### 当前验证

- 聚焦组合回归：`13 passed in 0.63s`。
- 全仓回归（所有本轮改动后）：`615 passed, 3 warnings, 9 subtests passed in 49.81s`；警告为既有 `TestProtocol` pytest 收集警告。
- 编译检查：`./scripts/local-env.sh python -m compileall -q client/app/packaged_entry.py client/app/institution_access.py client/tests/test_ray_101_packaged_composition.py`，退出码 0。
- `git diff --check`：本轮组合根、访问页和测试文件退出码 0。
- 全量 JUnit：[`pytest-full-packaged-composition-20260731.xml`](pytest-full-packaged-composition-20260731.xml)。

## 2026-07-31 P-05 五项正式预检组合

### 实现

- `client/app/preflight.py` 新增 `ProductionPreflightService` 与 `build_production_preflight(...)`，把一次已通过且带统计窗口的启动设备检查、`StateStore.evaluate_new_test(...)`、当前硬件规格的标定元数据和实际存储可用空间组合成 `PreflightPort`。
- 五项检查分别输出 `device_connected`、`storage_space`、`calibration_status`、`network_gate`、`zero_load`，每项有单独的通俗状态、稳定错误编号和唯一的“重新检查”恢复动作。
- `client/hardware_standardization/runtime.py` 只公开版本化的标定 profile 与 validation 标识，不泄露具体硬件适配器。当前 DO-P4864 配置为 `MVP_SCREENING_ESTIMATED_V1`，UI 明确显示“筛查估算标定配置已加载”，不宣称完成正式物理标定。
- `client/app/qt_shell.py` 的 P-05 从四行扩展为五行，新增“设备零载”；完成提示同步为“五项预检已通过”。
- `client/app/fixture_replay.py` 明确把回放的标定和零载显示为“回放模式，不适用”，不会利用 fixture 伪造真机通过。
- 修正 `StateStore` 与共享 RAY-100 策略之间的边界漂移：恰好 24 小时仍允许新检测，只有超过 24 小时才阻断。

### RED / GREEN 证据

1. 正式 P-05 组合模块缺失：测试收集报 `ModuleNotFoundError`。
2. 24 小时边界测试发现客户端在恰好 24 小时误阻断：预期 ready、实际 `E-NET-001`；修正后通过。
3. 磁盘不足、未批准标定、启动空载失败三条分支经变异测试分别真实失败 `3 failed`，恢复判断后通过。
4. 正式 builder 缺失：`ImportError: cannot import name build_production_preflight`；接入当前硬件标定元数据后通过。
5. 回放零载行缺失：`KeyError: zero_load`；增加明确“不适用”状态后通过。
6. 截图视觉检查发现五行页面仍写“四项预检已通过”，回归测试按预期失败；文案修正后通过。

### 工件与边界

- 聚焦 JUnit：[`pytest-production-preflight-20260731.xml`](pytest-production-preflight-20260731.xml)，结果 `28 passed in 13.65s`。
- 最终四阶段本机工件：[`local-four-stage-p05-v2-20260731/`](local-four-stage-p05-v2-20260731/)；机器摘要 [`summary.json`](local-four-stage-p05-v2-20260731/summary.json) 为 `PASSED`，1,658 帧、四阶段、P-01～P-11 全部实际访问。
- 最终 P-05 截图：[`04-preflight.png`](local-four-stage-p05-v2-20260731/04-preflight.png)，SHA-256 `d51ac5fcfce4befa2c1ca33da09c3aa67947dec439224956a80e4fcb59e914a0`。
- 视觉 RED 工件保留于 `local-four-stage-p05-visual-red-20260731/`，用于证明“四项”旧文案曾被实际截图捕获，不作为最终验收图。
- 第一次全仓回归发现旧端到端测试仍硬编码四项，结果 `1 failed, 621 passed`；测试随后改为断言五个明确 key，而非只改数字。最终全仓 JUnit [`pytest-full-p05-20260731.xml`](pytest-full-p05-20260731.xml) 为 `622 passed, 3 warnings, 9 subtests passed in 55.18s`。
- 真机连接与五秒空载沿用 RAY-113/RAY-115 受控现场证据；真实磁盘耗尽安全结果沿用 RAY-86。当前新增工件验证本地组合、门槛边界和 UI，不重复宣称进行新的硬件试验。
- 仍不证明：经过制造/临床批准的物理标定、真实网络监控自动解锁、目标 Windows 上的非技术操作员可用性、生产 License/云端联调。RAY-101 因最后的操作员验收项继续保持 `In Review`。
