# RAY-92 Evidence

- Issue：`RAY-92` 受试者标识、选填档案与简短授权
- URL：https://linear.app/ray-app/issue/RAY-92/受试者标识选填档案与简短授权
- 初次抓取时间：2026-07-20T08:54:41Z
- 开始实现时间：2026-07-20T09:30:00Z
- 初次抓取状态：Backlog
- 当前工作流状态：In Review（2026-07-20T09:54:37Z 写入并重新读取确认）
- 里程碑：P2：一键筛查
- 优先级：High
- 关系：与 `RAY-101` 相关；无阻塞/被阻塞关系

## 验收条目快照

- [x] 支持档案号、病历号、体检号、住户编号等机构编号
- [x] 编号只在固定机构范围查找、去重和关联历史
- [x] 支持无机构编号的非实名快速建档
- [x] 姓名、身份证和联系方式不必填；首版不要求身份证
- [x] 年龄、性别、身高、体重、基础情况和既往损伤选填
- [x] 选填字段区分已填写、明确无、未知、拒绝提供、不适用
- [x] 首次建档简短授权，相同用途复用；策略或数据范围实质变化重新确认
- [x] 档案冲突不自动合并
- [x] 访问和导出经固定机构作用域与审计端口；适配器跨机构返回会被拒绝

## 实现文件与关键决策

- `client/workflow/participant.py`：机构编号 DTO、机构边界、冲突/未找到/唯一命中分支、匿名建档、字段缺失语义、访问与导出审计端口。
- `client/workflow/consent.py`：策略版本、用途与数据范围快照；必要用途和可选研究用途分离；精确匹配时复用，否则重新确认。
- `client/workflow/models.py`、`ports.py`、`coordinator.py`：将 `subject_uuid + consent_record_id` 作为不可缺失的会话创建上下文；未绑定时以 `E-AUT-001` 阻止采集。
- `client/app/controller.py`、`qt_shell.py`：接通 P-02～P-04 的查找、建档、选填档案、授权与预检；保留未配置 RAY-92 依赖时的 RAY-101 兼容路径。
- `client/tests/test_ray_92_*.py`：领域、端口、控制器和 Qt 表单覆盖；`client/tests/test_ray_101_coordinator.py` 更新会话端口测试桩以适配新增上下文。

关键决策：客户端从构造时固定的 `tenant_id`/`issuer` 发出端口请求，不接受 UI 传入租户；冲突永不自动选择或合并；非 `PROVIDED` 字段不得携带值；研究授权不预选且不影响必要筛查用途；客户端不直接访问数据库、HTTP 或串口。

## 验证命令与逐项结果

执行时间：2026-07-20T09:53:00Z。

```bash
QT_QPA_PLATFORM=offscreen /private/tmp/feetforceplate-subtask-b-venv/bin/python \
  -m pytest client/tests -q \
  --junitxml=docs/evidence/linear/RAY-92/pytest-results.xml
```

结果：`48 passed`（RAY-92 自动测试及 RAY-101 回归；最终提交前会再次新鲜运行并以 XML 为准）。

```bash
/private/tmp/feetforceplate-subtask-b-venv/bin/python -m compileall -q \
  client/app client/workflow client/tests
```

结果：通过。

```bash
! rg -n "^(import|from) (serial|sqlite3|requests|httpx|urllib|aiohttp)" \
  client/app client/workflow client/local_analysis client/reporting
```

结果：0 命中，客户端仍只依赖端口。

界面证据（Qt `offscreen` 自动渲染并已目视检查，不等同于现场人工验收）：

- [P-02 机构编号与掩码命中](P-02-subject.png)
- [P-03 选填档案与缺失状态](P-03-profile.png)
- [P-04 必要/可选授权分离](P-04-consent.png)

## 自动测试、真机与人工边界

- 已自动验证：四种机构编号类型、空编号拒绝、租户越界拒绝、冲突不自动合并、匿名建档无身份信息、字段状态守恒、访问/导出审计调用、授权复用/重确认/拒绝、授权与受试者绑定后才可建会话、Qt 表单与控制器主路径。
- 尚未验证：真实存储适配器的跨机构隔离和历史关联；真实审计落库/导出记录；机构实际授权文本与法务确认；目标 Windows 设备上的 1280x720/高 DPI/键盘操作；现场操作员对 P-02～P-04 的人工可用性与误操作验收。
- 因上述外部/人工项未完成，本 issue 只能进入 `In Review`，不得标 `Done`。

## 失败或限制

- 当前 UI 截图来自 macOS Qt offscreen；P-03 在 720px 高度内容较密，需在目标 Windows 上确认滚动/缩放策略和可读性。
- 真实 `SubjectPort`、`ConsentPort`、`AuditPort` 与 `SessionPort` 由其他模块提供；本 issue 只实现契约和客户端编排，未直接操作其私有存储。
- 报告导出审计在存在已选受试者和版本化报告引用时调用；真实导出与审计原子性需由适配器集成测试验证。

## 关联提交

- 实现与本 evidence：`53de745d72fd660cd4afd13a1e6f7fbc4a962b2d`。
- SHA 回填：`52bacb4981b28ea67f46083f7b5ea2e73b841a07`。
