# RAY-115 Evidence — 启动校验失败恢复、内部日志与验收证据

## Issue snapshot

- Linear issue: RAY-115
- Status captured during implementation: `In Progress`
- Dependencies: RAY-113 and RAY-114 (`In Review`)
- Approved design: `docs/superpowers/specs/2026-07-21-startup-device-validation-design.md` (`7c089a9`)
- Structured snapshot: `issue-snapshot.json`

## Implementation

- `client/spool/state_store.py`
  - additive SQLite schema migration 1 → 2;
  - durable `device_validation_runs` table for versioned safe summaries;
  - separate `telemetry_events` queue with PENDING / UPLOADING / ACKNOWLEDGED / QUARANTINED states;
  - interrupted UPLOADING telemetry is returned to PENDING with an incremented attempt count.
- `client/startup_validation/persistence.py`
  - canonical JSON allow-listed from `DeviceValidationRun.safe_summary()`;
  - rejects raw device paths and accepts only opaque terminal/device references;
  - atomically saves the local audit row and queues the upload event;
  - upload failure changes only queue state and never mutates the local validation result.
- `client/startup_validation/recovery.py`
  - versioned `startup-failure-escalation/1` policy;
  - the third consecutive signal-class failure becomes `SERVICE_REQUIRED`;
  - pass, stream, connection, or load conditions break/do not enter the signal escalation chain.
- `client/startup_validation/workflow.py`
  - applies the versioned policy before writing the audit record;
  - records successful, service, device-discovery, occupied-device, and internal-error runs;
  - blocks the workbench for every non-PASS outcome.
- `client/app/packaged_entry.py`
  - production package composition opens the persistent local state database;
  - injects the audit trail and persisted-history escalation policy into the mandatory gate;
  - does not attempt network upload on the startup critical path.
- `client/app/startup_validation.py`
  - customer-safe SERVICE_REQUIRED page and all requested recovery pages;
  - stable diagnostic number, one primary recovery action, safe exit, and no protocol/debug details.
- `scripts/capture_startup_failure_states.py`
  - deterministic capture of all seven public failure/recovery states.

Implementation commit: `ef26fdb7447ed951ab9322a4dc08bc746675c617`

## Automated verification

Primary failure, persistence, startup, device, and spool matrix:

```text
./scripts/local-env.sh python -m pytest \
  tests/startup_validation tests/device tests/spool \
  client/tests/test_ray_114_startup_ui.py \
  client/tests/test_ray_114_packaged_gate.py \
  client/tests/test_ray_114_packaged_entry.py \
  -q --junitxml=docs/evidence/linear/RAY-115/pytest-results.xml
```

Result: **102 passed**. JUnit: `pytest-results.xml`.

Existing workbench UI compatibility:

```text
./scripts/local-env.sh python -m pytest \
  client/tests/test_ui_design_system.py \
  client/tests/test_ui_demo.py \
  client/tests/test_ui_read_models.py \
  client/tests/test_ray_101_qt_shell.py \
  client/tests/test_ray_101_controller.py \
  -q --junitxml=docs/evidence/linear/RAY-115/pytest-ui-regression-results.xml
```

Result: **27 passed**. JUnit: `pytest-ui-regression-results.xml`.

Full repository regression:

```text
./scripts/local-env.sh python -m pytest -q \
  --junitxml=docs/evidence/linear/RAY-115/pytest-full-regression-results.xml
```

Result: **215 passed**. JUnit: `pytest-full-regression-results.xml`.

Covered automatically:

- no device, occupied device/open race, load, disconnect, no data/stall, low rate, large host gap, fixed area, saturation, no variation, local anomaly, noise, drift, internal exception, retry, and later success;
- partial 5-second windows are marked discarded and never pass;
- retry starts a fresh connection/run and retains only audit linkage;
- stable `E-INI-006` with unique diagnostic IDs and no exception message in public copy;
- SQLite schema-1 upgrade to schema 2 without dropping existing tables;
- local safe summary + upload event atomicity, upload-failure requeue, and startup recovery;
- pass/non-signal reset and third consecutive signal failure escalation;
- one recovery button, safe exit, no skip, and no CheckSum, threshold, bad-point, stack, raw port, or trace text in customer UI.

## Safe log example and privacy review

- Sample: `safe-telemetry-sample.json`
- Contains only opaque run/terminal/device references, versions, outcome/reason/error/diagnostic codes, timestamps, bounded aggregate statistics, transitions, and partial-window flag.
- Does not contain names, institution record numbers, raw serial paths, raw matrices, per-sensor bad-point detail, threshold values, protocol error text, debug curves, or stack traces.
- The threshold and failure policy are logged by version identifier, not by mutable numeric values.

## Repeatable UI capture and visual review

```text
./scripts/local-env.sh python scripts/capture_startup_failure_states.py \
  --output-dir docs/evidence/linear/RAY-115/ui
```

Reviewed 1440×900 captures:

- `ui/device-not-found.png`
- `ui/device-busy.png`
- `ui/load-not-empty.png`
- `ui/stream-interrupted.png`
- `ui/signal-invalid.png`
- `ui/service-required.png`
- `ui/internal-error.png`

Visual review result: all states remain within the existing Steady Health shell, show one plain-language recovery action and safe exit, keep the stable diagnostic number readable, and do not expose internal details. No clipping or overflow was observed. RAY-114 separately records 1280×720 long-copy and 2× Qt scale-factor capture.

## Verification boundary

Automated failure injection, local persistence, queue state behavior, and local visual review are complete. The following remain explicitly unverified:

- repeated cold starts and fault injection on a real DO-P4864;
- physical load during collection, real cable removal/reconnection, and proof from live device logs;
- Windows target with CH340 driver, Windows high DPI, keyboard-only, screen reader, and safe-exit acceptance;
- clinic/elder-care operator usability;
- a real telemetry upload worker/server, authentication, retry/backoff, and server acknowledgement end to end;
- signed installer, upgrade/rollback, and database migration on the target OS.

Therefore RAY-115 may move to **In Review**, not Done.

## 2026-07-26 发布阻断复核

- 修复：`StartupValidationCoordinator` 在调用可能失败的 audit/SQLite sink 前先保留本次运行。sink 失败会呈现安全的 `INTERNAL_ERROR`，阻止进入工作台；`retry()` 仍带前一次 run ID，重新连接并创建新运行。
- 测试：新增 audit 写入失败 → 新连接 → 后续成功的链路断言；定向 **22 passed in 0.49s**，启动/设备/入口组合 **112 passed in 1.00s**，全量 **336 passed in 28.03s**。
- 限制：未进行真机故障注入、真实 SQLite 损坏恢复、Windows/CH340 或遥测服务端确认；RAY-115 保持 In Review。
- Commit SHA：尚未创建；本轮未暂存。

## 2026-07-31 真机正常路径基线（部分验收）

复用 RAY-114 的无受试者真机运行，汇总 SHA-256 为 `aa53315b4b277d44d61a555a2087be5de931f30b69c77e10a3bf2847d45b00e4`。原始帧、加密分段、串口路径及本地测试密钥均只留在 `/private/tmp`，本 evidence 不含这些信息。

- 一次真实 CH340/DO-P4864 冷启动等价路径完成 5.139 秒空载基线（110 帧）和 10 秒采集（208 帧）。
- 会话完成后为 `VALID` 且已提交；以新 `StateStore` 打开并执行 `RecoveryScanner`，未发现需要隔离、恢复、重排或标记中断的条目。
- 该结果仅证明正常路径中的本地提交和重启恢复扫描；它不等价于启动 UI 的审计日志/遥测上传验收。

仍待真实故障验收：多次冷启动、采集中施加载荷、拔线、重连、端口占用、日志上传失败与客户 UI 安全提示；以及 Windows 高 DPI、键盘/读屏、操作员和签名包。RAY-115 保持 `In Review`，未修改任何 Linear 完成勾选。

## 2026-07-31 真机端口占用故障注入（部分验收）

使用 `scripts/run_startup_gate_hardware_acceptance.py --occupy-connected-device --expect-state DEVICE_BUSY` 在无受试者条件下独占打开已连接 CH340 端口，但不读取任何帧；随后运行实际 `MandatoryStartupGate`。

- 汇总生成时间：`2026-07-31T07:49:34Z`；summary SHA-256：`1f71e5f40585974313dac273b0cdd9dc5c43f91fbb4f28c56c3165207dc05e58`。
- 观察状态：`BOOTSTRAPPING → DEVICE_BUSY`；`workbench_created=false`，`timed_out=false`，故障注入标记为 `PORT_HELD_OPEN`。
- 端口占用在测试退出时释放；没有创建受试者、筛查会话、原始帧、报告或遥测上传。

本节覆盖“端口被占用时提示关闭占用程序后重试”的真实设备路径；尚未覆盖载荷、流中断/拔线/重连、重复失败升级、日志上传、Windows/无障碍/操作员。RAY-115 保持 `In Review`。

## 2026-07-31 当前故障注入、持久化与恢复矩阵

同一启动矩阵运行 `144 passed in 0.91s`；JUnit SHA-256：`c4f97abfcdd23db6b78df8005a36bf599f14ae4639059b89b9c89f2eb2ef6428`（`tests=144`、`failures=0`、`errors=0`）。覆盖无设备、占用、载荷、断线/卡帧、饱和、噪声、内部异常、重试、版本化安全审计、上传失败重排和启动恢复的自动故障注入。它覆盖 RAY-115 的自动故障注入验收项，但不能替代载荷/拔线/重连的真机故障操作、Windows 或人工验收。

## 2026-07-31 真机多次冷启动（部分验收）

在相同空载 CH340/DO-P4864 上，使用启动门验收脚本完成三次独立进程启动；所有 summary 均仅包含公共状态和是否创建工作台。

| Run | 时间（UTC） | 结果 | Summary SHA-256 |
|---|---|---|---|
| 1 | 07:46:57 | `PASSED`，创建工作台，未超时 | `c1dc6d81d94dfc56020af28f46844d1274267ea52adf2a6074af3fb91c1d9efa` |
| 2 | 07:53:53 | `PASSED`，创建工作台，未超时 | `efe1c4621cd5c30525dde4ff77c38579471dd5f3f8751de6f44d6e9e8c8b9cad` |
| 3 | 07:54:14 | `PASSED`，创建工作台，未超时 | `c64983fb44e813964f5c7d2d75b4356e2910c9fed890b4cfdcf7c80073dc29c7` |

三次均执行实际 5 秒空载校验；快速异步状态有时未被轮询单独采样，但最终 `PASSED` 与 `workbench_created=true` 一致。此证据覆盖“真机多次冷启动验证完整 5 秒窗口”；不覆盖载荷、拔线/重连、Windows、人工或遥测端到端，RAY-115 保持 `In Review`。

## 2026-07-31 已加载条件下的异常通过（未通过验收）

现场确认设备表面已放置非人体测试载荷后，运行启动门验收并明确期望 `LOAD_NOT_EMPTY`。结果与预期不符：脚本退出码为 2（期望状态不匹配），但实际状态为 `PASSED`，且 `workbench_created=true`、未超时。

- 汇总生成时间：`2026-07-31T08:19:49Z`；summary SHA-256：`b3a3f75319e9e46fb8dfd8a189f958de400709d5152d505009e47560c7bde2ba`。
- 采样状态为 `BOOTSTRAPPING → WAITING_FOR_EMPTY → COLLECTING_BASELINE → PASSED`，没有产生 `LOAD_NOT_EMPTY`。
- 本 evidence 不包含载荷类型、重量、位置、原始帧、阈值或串口路径。

因此“检测到载荷时提示清空设备，并在条件满足后重新采集完整 5 秒”保持未勾选。该结果须在确认载荷覆盖有效感应区且具有足够稳定信号后，以受控载荷重新测试；在复现并定位前，不得以当前空载门限宣称载荷安全验收完成。

## 2026-07-31 重新放置后重复异常通过（未通过验收）

在将同一非人体测试载荷重新放置后，以相同的实际启动门命令再次明确期望 `LOAD_NOT_EMPTY`。结果再次与预期不符：脚本退出码为 2（期望状态不匹配），实际仍为 `PASSED`，并创建了工作台。

- 汇总生成时间：`2026-07-31T08:23:52Z`；summary SHA-256：`804d148133bb21d646feb91c3009b5f0b6959cb60229aa4c24a4c5914972d98a`。
- 观察状态：`BOOTSTRAPPING → WAITING_FOR_EMPTY → COLLECTING_BASELINE → PASSED`；`workbench_created=true`，`timed_out=false`。
- 汇总未保存载荷类型、重量、位置、原始帧、阈值、串口路径或受试者资料。

两次不同放置尝试均异常通过，故不能再将问题归因于单次边缘放置。保持该验收项未勾选、RAY-115 保持 `In Review`；在任何阈值或门禁逻辑改动前，须先进行仅输出检测器命中状态与命中帧计数的脱敏诊断，以区分“未形成有效传感信号”和“判定实现失效”。

## 2026-07-31 空载检测器对照（诊断前置，不构成载荷验收）

操作员确认清空测试载荷后，使用 `scripts/run_startup_load_detector_diagnostic.py --duration-seconds 5 --expect-result NOT_DETECTED` 通过生产 CH340 发现与解析边界读取了 5 秒；不启动 UI 或筛查会话。

- 汇总生成时间：`2026-07-31T08:30:15Z`；summary SHA-256：`e22bfcce3f9f207814bc5dcad30d1e32840ca82b3a5766ef67b62d2278c002ed`。
- `terminal_status=COMPLETED`，`valid_frame_count=106`，`detector_result=NOT_DETECTED`；两个保护条件的命中帧数均为 0。
- 汇总不含原始帧、设备路径、阈值数值、载荷位置/重量、受试者资料或凭据。

该对照仅确认当前空载运行未被诊断工具误报；下一步必须在受控非人体载荷下运行相同工具并期望 `DETECTED`。在该对比完成前，RAY-115 的真实载荷验收项保持未勾选。

## 2026-07-31 受控载荷检测与同一门禁清空后重试（已通过该条恢复验收）

先以稳定的非人体测试载荷运行生产解析器诊断：`COMPLETED`、106 个有效帧、`DETECTED`，两个载荷保护条件均在全部 106 帧命中；diagnostic summary SHA-256：`a4f00b4a5c9f76f9f5000cf4e993993a0b28fa38b236fccf60db65e2b867986d`。随后实际启动门单次进入 `LOAD_NOT_EMPTY`，未创建工作台；summary SHA-256：`0eb8025818325e5d901fbfce3362c9a49fe8ab898c43a4b534dc5fce4f2aad81`。

最后使用同一 `MandatoryStartupGate` 完成连续受控验收。首次有载运行状态为 `BOOTSTRAPPING → WAITING_FOR_EMPTY → LOAD_NOT_EMPTY`，`workbench_created=false`；操作员确认清空后，同一实例执行 retry，第二次状态为 `WAITING_FOR_EMPTY → COLLECTING_BASELINE → PASSED`，`workbench_created=true`，两次均未超时。连续运行 summary SHA-256：`ba6311de057c2d236fa5cd7331c79447743514b273980bfa04b3744d14609625`。

- 运行仅保存公共状态、是否创建工作台、检测器命中计数和版本标识；不保存原始帧、路径、位置、重量、阈值数值、受试者资料、报告或凭据。
- 该结果覆盖“检测到载荷时提示清空设备，并在条件满足后重新采集完整 5 秒”。此前两次不同放置条件下的异常通过仍保留在本 README 的失败证据中；本次受控配置证明可被实际门禁拦截和恢复，但不倒推或掩盖此前条件的物理原因。
- RAY-115 其余真机断线/重连、日志上传、Windows、无障碍、人工和 Evidence 完整性项仍未完成，故 issue 保持 `In Review`。

## 2026-07-31 真机受控进程中断与新进程恢复（部分验收）

在已清空的真机上运行本地硬件采集；在采集期内由父进程受控终止子进程，随后使用新的 `StateStore` 和启动恢复扫描。重跑后的隐私安全汇总 SHA-256：`b23e36aa816281a7cf4abe3f783dcadcef219fdc34e2e8f0960f21830707b51b`。

- 受控中断已发生（子进程返回 `-9`）；恢复扫描丢弃 `1` 个中断中的暂存。
- 恢复后正式 `sessions`、`segments` 和 `artifacts` 计数均为 `0`；没有恢复、注册或复用旧运行的结果。
- 汇总不含串口路径、原始帧、身份、密钥或子进程输出。此前发现旧脚本汇总会带入串口路径，已在本轮修复后重跑；定向隐私回归 `2 passed`。

该结果覆盖“恢复后不复用旧运行的计时、帧或校验结论”的真机进程中断路径。它不替代采集中真实施加载荷、拔线和重连，也不覆盖 Windows、人工、上传或完整证据项。

## 2026-07-31 真机载荷、拔线与重连（已通过组合验收）

本项的载荷子场景由上文“受控载荷检测与同一门禁清空后重试”覆盖：真实启动校验门在有载时阻止进入工作台，清空后才重新完成完整窗口。随后在空载无受试者采集中，由操作员真实拔线并重新插回。

- 拔线运行 summary SHA-256：`0438afe33fb6a0b43c2a5f55732cfcdcdbc7296b4107c25a95d9891b0b228fb5`。结果为 `TRANSPORT_DISCONNECTED`、`INVALID`、`committed=false`；重启扫描没有恢复、注册或保留正式会话/派生物。
- 重连后独立新运行 summary SHA-256：`7f8192a647ef2c9771bc5dba06f649dbc16c6c86fa230bea90f307cfec8d72ea`。其重新完成 5 秒基线和 10 秒采集，结果 `VALID`、`committed=true`，重启扫描干净。
- 两份汇总均不包含设备路径、原始帧、密钥、受试者资料或底层异常文本；断线原因只以稳定安全码表示。

该组合证明载荷校验、真实拔线导致的无效且未提交运行，以及重连后的独立新运行均不沿用旧数据。它不覆盖 Windows/无障碍、遥测上传、客户界面人工审阅或 Evidence 完整性项；RAY-115 继续保持 `In Review`。

## 2026-07-31 真机失败审计与隐私边界（部分验收）

在私有临时状态库中，以真实 CH340 端口占用触发实际 `MandatoryStartupGate` 的 `DEVICE_BUSY`。汇总 SHA-256：`077c0ee00f50686fcaa6666f4033f578993e0b92e9ff538abe19708e2a62b911`。

- 客户门禁状态为 `BOOTSTRAPPING → DEVICE_BUSY`，未创建工作台、未超时；没有读取压力帧。
- 本地审计生成 1 条待补传的版本化记录，结果为 `RETRYABLE_FAIL`，原因码为 `DEVICE_BUSY`；汇总仅报告记录计数、结果/原因码、schema 版本和允许字段检查。
- 允许字段检查通过：没有设备路径、原始帧、矩阵或堆栈详情。规则/阈值仅以版本标识存在，未输出数值。
- 发现并修正了初版检查把允许的 `thresholds` 版本标识误判为敏感字段的问题；修正后定向 `20 passed`。

该运行是脱敏审计和安全失败路径的真机证据，不替代目标 Windows/高 DPI、键盘/读屏、客户页面人工审阅或真实遥测上传端到端。相应 Linear 项仍保持未勾选，RAY-115 保持 `In Review`。

## 2026-07-31 本机可验收项收口

本轮没有新增硬件运行，也没有把工程回放或自动测试表述为新的真机证据。它把既有实现、自动故障注入、七态客户页面截图，以及上文已经完成的真实端口占用、载荷、拔线和重连证据逐条映射回 Linear 验收项。

当前专项验证命令：

```text
./scripts/local-env.sh python -m pytest \
  tests/startup_validation tests/device tests/spool \
  client/tests/test_ray_114_startup_ui.py \
  client/tests/test_ray_114_packaged_gate.py \
  client/tests/test_ray_114_packaged_entry.py \
  -q --junitxml=docs/evidence/linear/RAY-115/pytest-local-closeout-20260731.xml
```

结果：**147 passed in 2.81s**；JUnit SHA-256：`dfa77aec8d8b18ee76cc2d54fbebb195c6ba3b9ff066303d1708745fb4be8823`。随后全仓回归为 **622 passed，3 个既有 collection warnings，9 subtests passed in 58.59s**；JUnit SHA-256：`8d59ba120a6e294c989e8fe44831c6d48ad38b99e70e7eae21973dcd9512fa86`。验证时仓库 HEAD 为 `4fc33ee023013a1c6a0f3e9c906b4e5d41d4ef52`，工作树包含尚未提交的 P2 收口改动，因此该 SHA 只作为基线标识，不把当前工作树冒充为已提交版本。

本轮可勾选的条目及证据映射：

- 无设备：`DEVICE_NOT_FOUND` 客户态只有“重新连接”主动作，且任何失败都不创建工作台。
- 数据流中断：自动故障注入证明部分窗口被标为 discarded 且不能通过；上文真机拔线运行以 `TRANSPORT_DISCONNECTED / INVALID / committed=false` 结束，重连后创建独立新运行。
- 重复失败：版本化 `startup-failure-escalation/1` 策略在第三次连续信号类失败后进入 `SERVICE_REQUIRED`，通过、连接、载荷和流中断不会错误累计。
- 非预期错误：客户页使用稳定 `E-INI-006`、每次运行独立诊断编号、单一重试动作和安全退出，不显示异常文本。
- 脱敏审计：SQLite 保存版本化 `DeviceValidationRun` 安全摘要、状态迁移、原因码、规则版本和有界统计；真实 `DEVICE_BUSY` 审计验证了允许字段集合。
- 内外信息隔离：坏点、阈值数值、协议错误、原始曲线、端口和堆栈均不进入客户页面或补传 payload；内部判断只通过版本和稳定码关联。
- 客户恢复页面：七个失败态截图及 Qt 测试均证明只有一个主要恢复动作并保留安全退出。
- 补传失败与本地门禁解耦：审计与待传事件原子落盘；上传失败只把事件重排为 `PENDING`，不修改本地校验结果；启动关键路径不等待网络上传。
- 内部日志可定位且客户界面不泄漏：真实端口占用审计可由结果、原因、规则版本、诊断编号和状态迁移定位，同时客户页泄漏词检查通过。
- Evidence 完整性：本文件包含命令、JUnit、日志字段审计、七态截图、真机环境与 SHA、结果、失败历史、限制和实现 commit。
- Linear 回填：本轮在 RAY-115 和父 issue RAY-101 同步 evidence 路径、完成项和剩余边界。

截至 2026-07-31 仍不勾选两项：真实 telemetry worker/server 的认证、退避与服务端确认尚未端到端接入；Windows 高 DPI、键盘、提示文字和退出路径仍需目标机人工验收。因此当时 RAY-115 保持 `In Review`，不能标 `Done`。

## 2026-08-02 自动脱敏故障日志补传收口

本轮补齐了之前明确缺失的软件链路，未使用或模拟新的硬件证据：

- 机构登录成功后，正式 packaged entry 自动启动独立后台 worker；启动校验和进入工作台均不等待网络。
- 每次出站前重新按 `extra=forbid` 的版本化契约校验，只允许不透明 UUID/设备引用、版本、稳定结果/原因/错误码、时间、状态迁移和有界聚合统计。含 `institution_record_number` 等额外字段的历史污染事件会在发请求前进入 `QUARANTINED`。
- 客户端使用当前机构 Bearer token；服务端把 token 中的 tenant、client installation 和上传权限与批次绑定，不接受跨安装实例补传。
- 离线/服务错误只把事件重排为 `PENDING`，不修改不可变本地校验审计；后台按 30 秒起步、最高 300 秒的有界指数退避重试，进程重启会恢复中断的 `UPLOADING` 事件。
- seed API 仅在私有不可变文件持久化成功后返回严格 event acknowledgement；相同事件在重新打开 repository 后仍幂等。持久化文件权限为 `0600`，自动测试同时检查未出现姓名或机构档案字段名。

可复核 evidence：`telemetry-closeout-20260802.json`。聚焦矩阵为 **88 passed**，JUnit `pytest-telemetry-closeout-20260802.xml`，SHA-256 `073ae8e9f5224e586c8d2feb3f121dded81caba2e7ad41584bee1812ea1217d3`。全仓回归为 **778 passed、1 skipped、3 个既有 collection warnings、21 subtests passed**，JUnit `pytest-full-telemetry-closeout-20260802.xml`，SHA-256 `72dd4a8924420ff2bf837b0efb684d6c902e38db4cf5cd86cd5326a3055899a5`。Ruff、Mypy、compileall 与 `git diff --check` 均通过。

由此可勾选“故障日志默认自动补传，但不包含姓名、机构档案号或未脱敏客户数据”。证据仅证明本机软件实现、认证 ASGI 集成、私有持久化与重启幂等；不声称真实部署网络可用性、Windows 人工验收、机构操作员验收、生产授权或临床验证。RAY-115 仍须保持 `In Review`，唯一未完成项为 Windows 高 DPI、键盘、提示文字和退出路径人工验收。
