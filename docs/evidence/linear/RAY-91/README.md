# RAY-91 Evidence

- Issue：`RAY-91` 标准筛查协议、引导流程与基础结果
- URL：https://linear.app/ray-app/issue/RAY-91/标准筛查协议引导流程与基础结果
- 初次抓取时间：2026-07-20T08:54:41Z
- 开始实现时间：2026-07-20T09:56:31Z
- 初次抓取状态：Backlog
- 当前工作流状态：Done（2026-07-31T15:20:29Z：8/8 验收项、证据评论及两项附件均已重新读取确认）
- 里程碑：P2：一键筛查
- 优先级：Medium
- 关系：无阻塞/被阻塞；重新读取时 related issue 为 `RAY-92`、`RAY-101`

## 验收条目快照

- [x] `protocol_id/version` 定义站位、时长、开始/结束条件和质量门槛
- [x] 自动检查、站位引导、自动倒计时、采集、本地处理
- [x] 一个主操作和一个明确停止动作（停止需一次简短确认）
- [x] 提示文字与音频 cue 配置进入版本化协议；实际音频播放待目标机验证
- [x] 四段回放结果写入版本化、加密的 `LocalAnalysisResult`，并仅在有效时生成 `BASIC_READY` 调试报告
- [x] 无效会话重测且不生成报告
- [x] 扩展范式必须同时独立验证且经 Feature Flag 开放
- [x] 参考范围发布门控要求适用人群、来源、版本、审批人和审批时间

## 实现文件与关键决策

- `client/workflow/protocol.py`：标准/扩展协议 DTO、协议快照、起止条件、质量检查清单、提示配置、Feature Flag+验证双门控、参考范围审批门控和站位倒计时控制器。
- `client/workflow/coordinator.py`、`models.py`、`ports.py`：默认标准协议注入；预检后重置站位门控；接触与有效区域满足后允许手动开始，稳定 3 秒自动开始；会话端口接收不可变协议快照；按配置时长自动结束并进入本地质量处理。
- `client/app/controller.py`、`qt_shell.py`：设备适配器可经事件方法提交站位与采集时间；P-06 显示数字+文字倒计时；P-07 显示协议提示/剩余时间且只保留停止；停止需二次点击确认；P-08 根据有效性只显示报告/下一位或重测。
- `client/tests/test_ray_91_*.py`：协议、扩展门控、参考范围、站位、协调器与 Qt 状态覆盖；RAY-101/RAY-92 测试桩更新协议快照端口。

关键决策：默认协议 `standard-static-bilateral@1.0.0-pilot` 的 30 秒采集和 3 秒稳定保持均明确标为 pilot 配置，不作为现场验证后的对外承诺；质量门控保存版本化检查项目，不在普通 UI 暴露内部阈值；睁闭眼、单足与 LOS 等扩展范式即使配置 Feature Flag，也必须先达到 `VALIDATED`。

## 验证命令与结果

执行时间：2026-07-20T10:05:41Z。

```bash
QT_QPA_PLATFORM=offscreen /private/tmp/feetforceplate-subtask-b-venv/bin/python \
  -m pytest client/tests -q \
  --junitxml=docs/evidence/linear/RAY-91/pytest-results.xml
```

结果：`60 passed`；包含 RAY-91 自动测试以及 RAY-101/RAY-92 回归。

```bash
/private/tmp/feetforceplate-subtask-b-venv/bin/python -m compileall -q \
  client/app client/workflow client/tests
```

结果：通过。

```bash
! rg -n "^(import|from) (serial|sqlite3|requests|httpx|urllib|aiohttp)" \
  client/app client/workflow client/local_analysis client/reporting
```

结果：0 命中。

界面证据（Qt offscreen、fixture 驱动并已目视检查，不等同于目标现场验收）：

- [P-05 自动检查](P-05-preflight.png)
- [P-06 站位与数字/文字倒计时](P-06-position.png)
- [P-07 协议提示、剩余时间与单一停止](P-07-acquiring.png)
- [P-08 BASIC_READY](P-08-basic-ready.png)

### 2026-07-23 四段真机工程回放基准

用户确认的完整测试口径为四段各 20 秒（总计 80 秒）：并足睁眼、并足闭眼、左脚在前串联、右脚在前串联。真机采集得到 1,658 个有效 48×64 帧；各段时长为 20.0749–20.0946 秒。`tandem_left_front` 采集期间出现 1 个无效候选帧，解析器已重同步且该候选不进入回放集；其余三段无无效候选帧。

原始串口字节仅留在本机临时受控目录，不进入仓库或 evidence。仓库提交的是去标识化、逐段 P99 相对归一化的 `uint8` 矩阵序列及聚合统计：

- [采集聚合记录](reference-protocol-capture-20260723.json)
- [回放 fixture 说明](../../../../tests/fixtures/device/dop4864_reference_protocol_v1/README.md)
- `tests/fixtures/device/dop4864_reference_protocol_v1/reference-poses.npz`

每次后续软件/UI 验证先运行这一回放集；只有它不能复现或需要考察连接、吞吐、串口异常等物理层问题时，才重新连接真机。

### 2026-07-23 测试资产归位

规范夹具已归位到根目录测试资产
`tests/fixtures/device/dop4864_reference_protocol_v1/`，由
`a85fee82922a436e33aa633c6b7a5b100a141f57` 提交。客户端旧路径保留为兼容副本，
回归测试会验证其 SHA-256 与规范夹具相同；新的测试消费者均从根目录测试资产读取。

验证命令：

```bash
UV_OFFLINE=1 UV_CACHE_DIR=/private/tmp/feetforceplate-uv-cache \
FEETFORCEPLATE_VENV=/private/tmp/feetforceplate-subtask-b-venv \
./scripts/local-env.sh python -m pytest \
  client/tests/test_ray_91_reference_protocol_fixture.py \
  tests/hardware_standardization/test_sensor_defect_repair.py -q
```

结果：`19 passed in 0.62s`。这仍是去标识化工程回放，未改变本 evidence 中的真机、临床和人工验收边界。

```bash
UV_OFFLINE=1 UV_CACHE_DIR=/private/tmp/feetforceplate-uv-cache \
FEETFORCEPLATE_VENV=/private/tmp/feetforceplate-subtask-b-venv \
./scripts/local-env.sh python -m pytest \
  client/tests/test_ray_91_reference_protocol_fixture.py -q
```

执行时间：2026-07-23。结果：`9 passed`（4 段 fixture 合同 + 4 段逐帧生产显示投影回放 + 参数化输入不变性）。连同 RAY-91 既有回归，命令 `client/tests/test_ray_91_reference_protocol_fixture.py client/tests/test_ray_91_protocol.py client/tests/test_ray_91_position_guidance.py client/tests/test_ray_91_coordinator.py client/tests/test_ray_91_qt.py` 结果为 `21 passed in 1.32s`。

### 2026-07-31 本地完成验收

本次补齐最后一个可在无硬件条件下完成的验收缺口：四阶段回放分析不再持久化专用 `V1DebugResult`，而是统一生成 `LocalAnalysisResult`。该对象包含独立的结果、算法和协议版本，完整帧数、质量状态、相对热图、客户/内部指标分区以及 withheld 原因；`LocalReplayStore` 以 `local-analysis-result/1` schema 双信封加密落盘。调试指标不会进入客户指标集合。

真实应用入口验证：

```bash
QT_QPA_PLATFORM=offscreen ./scripts/local-env.sh python main.py \
  --replay --verify --replay-speed 500 \
  --output-dir /private/tmp/feetforceplate-ray91-verify-20260731.1omm4F
```

结果：退出码 `0`，`summary.json` 状态为 `PASSED`、`local_only=true`；四阶段共 `1,658` 帧，分别为 `414/415/414/415`。产物包括 P-05 预检、四阶段采集、P-10 报告预览共 6 张 `1280×720` PNG、加密 SQLite、`report.pdf` 和 `summary.json`。六张截图均已逐张目视检查。

- `summary.json` SHA-256：`302e100275fe8cfe222b2db85dd08ebf52126169f2d699fedd94b2599cc70250`
- `report.pdf` SHA-256：`8cbb74e0121afd8e385f3f007b56bb05b162b2af062b7da40574a5f2162cccdc`
- fixture SHA-256：`2495b910bbf7e4fcca0cd0db36dde809f0fd6395bb6060eded44db575acd6f90`

从该次运行实际生成的 SQLite 密文记录重新打开并解密后，只输出非敏感验收字段：`schema_version=local-analysis-result/1`、`result_version=1`、`algorithm_version=v1-replay-debug/1.0.0`、`protocol_id=standard-static-bilateral`、`protocol_version=v1-replay-debug/1.0.0`、`source_frame_count=1658`、`quality_status=VALID`、`data_completeness=FOUR_STAGES_COMPLETE`、`relative_heatmap_shape=48×64`、`customer_metric_count=0`、`internal_metric_count=16`、`withheld_metric_count=16`，全部 withheld 原因为 `REPLAY_DEBUG_NOT_CUSTOMER_VALIDATED`。

当前代码回归：

```bash
QT_QPA_PLATFORM=offscreen ./scripts/local-env.sh python -m pytest -q \
  client/tests/test_ray_91_protocol.py \
  client/tests/test_ray_91_position_guidance.py \
  client/tests/test_ray_91_coordinator.py \
  client/tests/test_ray_91_qt.py \
  client/tests/test_ray_91_reference_protocol_fixture.py \
  client/tests/test_v1_debug_analysis.py \
  client/tests/test_v1_fixture_replay.py \
  client/tests/test_v1_local_end_to_end.py \
  client/tests/test_v1_replay_protocol.py \
  client/tests/test_v1_replay_ui.py \
  client/tests/test_v1_staged_coordinator.py \
  client/tests/test_local_replay_store.py \
  --junitxml=/private/tmp/feetforceplate-ray91-focused-20260731.xml
```

结果：`38 passed in 21.72s`；JUnit SHA-256 `cdf4fd006e3771f15665881d26132c6bd1e4958f60f5aa10c48969934fca2edf`。

```bash
QT_QPA_PLATFORM=offscreen ./scripts/local-env.sh python -m pytest -q client/tests \
  --junitxml=/private/tmp/feetforceplate-ray91-client-20260731.xml
QT_QPA_PLATFORM=offscreen ./scripts/local-env.sh python -m pytest -q \
  --junitxml=/private/tmp/feetforceplate-ray91-full-20260731.xml
```

结果分别为 `205 passed in 35.53s` 和 `593 passed, 3 warnings, 9 subtests passed in 37.75s`；JUnit SHA-256 分别为 `b83efbb664e71b2837a38cb958bbbfcd27e4ff57de0514ccd8772d26a37d7576`、`9245483e6740321f8cda716b73e0b24a8567d3993b245343d5649312d9c77a0f`。3 个 warning 均为既有 `TestProtocol` 类因自定义构造函数不被 pytest 收集，不是本次失败。

## 自动测试、真机与人工边界

- 已自动验证：协议快照字段；站位离开后倒计时复位；最小接触/有效区域门控；稳定保持后自动开始；手动开始守卫；协议时长到达后自动结束；VALID 生成版本化基础报告、INVALID 不生成；停止二次确认；扩展协议和参考范围的发布门控。
- 尚未验证：真实 DO-P4864 接触/有效区域信号与约 12 Hz 数据；预检适配器的真实并发耗时；30 秒/3 秒配置和站位文案的现场适用性；真实提示音播放、音量和养老院环境可听性；目标 Windows/高 DPI/键盘；真实操作员 P-05～P-08 可用性。
- 本次真机采集只验证了可回放的四段观察性工程输入；它不是闭眼/串联范式的独立临床或现场可用性验证，不能据此解除扩展协议的 Feature Flag/验证双门控。
- RAY-91 已证明版本化 `LocalAnalysisResult` 的四阶段回放生成、加密落盘、重开解密和 `BASIC_READY` 调试报告链路。RAY-90/RAY-85 仍分别负责可发布指标能力门控和正式本地分析/断网报告，不由本 issue 替代。
- RAY-91 的软件验收范围可独立完成；真实提示音音量、目标 Windows/高 DPI、操作员现场可用性、正式客户报告和临床适用性仍是其他 issue 或外部验收边界，不因本 issue 完成而被声明完成。

## 失败或限制

- PRD 将准确测试时长和站位指令列为后续验证项，因此代码使用 `1.0.0-pilot` 且 evidence 不把当前数值描述为已批准标准。
- 音频 cue 仅为端口前的配置合同；未直接调用系统音频 API，也未进行现场播放验证。
- P-05 截图使用预检结果 fixture；真实逐项/并行进度依赖设备、存储和同步适配器事件。

## 关联提交

- 实现与本 evidence：`68bbbeeed7e447a3100b03754ce196fc9c822864`。
- SHA 回填：`1155e048a273f383354105b1befbddfd67325b6d`。
- 本次回放 fixture、采集汇总与验证证据（实现提交）：`841b738c2f5381bfb755151b6146b42f58f10835`。
