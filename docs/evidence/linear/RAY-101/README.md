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
- 关联 implementation commit SHA：待提交后回填。
