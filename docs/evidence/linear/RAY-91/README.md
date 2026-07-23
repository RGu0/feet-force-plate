# RAY-91 Evidence

- Issue：`RAY-91` 标准筛查协议、引导流程与基础结果
- URL：https://linear.app/ray-app/issue/RAY-91/标准筛查协议引导流程与基础结果
- 初次抓取时间：2026-07-20T08:54:41Z
- 开始实现时间：2026-07-20T09:56:31Z
- 初次抓取状态：Backlog
- 当前工作流状态：In Progress（2026-07-23T07:59:41Z 重新开始四段真机工程回放基准采集；本次提交后转 In Review）
- 里程碑：P2：一键筛查
- 优先级：Medium
- 关系：无阻塞/被阻塞；重新读取时 related issue 为 `RAY-92`、`RAY-101`

## 验收条目快照

- [x] `protocol_id/version` 定义站位、时长、开始/结束条件和质量门槛
- [x] 自动检查、站位引导、自动倒计时、采集、本地处理
- [x] 一个主操作和一个明确停止动作（停止需一次简短确认）
- [x] 提示文字与音频 cue 配置进入版本化协议；实际音频播放待目标机验证
- [ ] 版本化 `LocalAnalysisResult` 具体模式由 RAY-85 实现；本 issue 已传递协议快照，并保持仅 VALID 才生成版本化 `BASIC_READY`
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
- [回放 fixture 说明](../../../../client/tests/fixtures/dop4864_reference_protocol_v1/README.md)
- `client/tests/fixtures/dop4864_reference_protocol_v1/reference-poses.npz`

每次后续软件/UI 验证先运行这一回放集；只有它不能复现或需要考察连接、吞吐、串口异常等物理层问题时，才重新连接真机。

```bash
UV_OFFLINE=1 UV_CACHE_DIR=/private/tmp/feetforceplate-uv-cache \
FEETFORCEPLATE_VENV=/private/tmp/feetforceplate-subtask-b-venv \
./scripts/local-env.sh python -m pytest \
  client/tests/test_ray_91_reference_protocol_fixture.py -q
```

执行时间：2026-07-23。结果：`9 passed`（4 段 fixture 合同 + 4 段逐帧生产显示投影回放 + 参数化输入不变性）。连同 RAY-91 既有回归，命令 `client/tests/test_ray_91_reference_protocol_fixture.py client/tests/test_ray_91_protocol.py client/tests/test_ray_91_position_guidance.py client/tests/test_ray_91_coordinator.py client/tests/test_ray_91_qt.py` 结果为 `21 passed in 1.32s`。

## 自动测试、真机与人工边界

- 已自动验证：协议快照字段；站位离开后倒计时复位；最小接触/有效区域门控；稳定保持后自动开始；手动开始守卫；协议时长到达后自动结束；VALID 生成版本化基础报告、INVALID 不生成；停止二次确认；扩展协议和参考范围的发布门控。
- 尚未验证：真实 DO-P4864 接触/有效区域信号与约 12 Hz 数据；预检适配器的真实并发耗时；30 秒/3 秒配置和站位文案的现场适用性；真实提示音播放、音量和养老院环境可听性；目标 Windows/高 DPI/键盘；真实操作员 P-05～P-08 可用性。
- 本次真机采集只验证了可回放的四段观察性工程输入；它不是闭眼/串联范式的独立临床或现场可用性验证，不能据此解除扩展协议的 Feature Flag/验证双门控。
- `LocalAnalysisResult` 的最终版本化模式、指标和落盘由后续 RAY-90/RAY-85 完成；本 issue 只保证协议快照进入会话端口、无效会话不出报告以及现有 `report_id/version` 行为。
- 因上述跨 issue、真机与人工项未完成，本 issue 只能进入 `In Review`，不得标 `Done`。

## 失败或限制

- PRD 将准确测试时长和站位指令列为后续验证项，因此代码使用 `1.0.0-pilot` 且 evidence 不把当前数值描述为已批准标准。
- 音频 cue 仅为端口前的配置合同；未直接调用系统音频 API，也未进行现场播放验证。
- P-05 截图使用预检结果 fixture；真实逐项/并行进度依赖设备、存储和同步适配器事件。

## 关联提交

- 实现与本 evidence：`68bbbeeed7e447a3100b03754ce196fc9c822864`。
- SHA 回填：`1155e048a273f383354105b1befbddfd67325b6d`。
- 本次回放 fixture、采集汇总与验证证据（实现提交）：`841b738c2f5381bfb755151b6146b42f58f10835`。
