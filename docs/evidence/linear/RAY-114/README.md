# RAY-114 Evidence — 启动设备初始化状态机与进度页面

## Issue snapshot

- Linear issue: RAY-114
- Status captured before implementation completion: `In Progress`
- Dependency: RAY-113 (`In Review`, implementation commit `0fd1b4d`)
- Approved design: `docs/superpowers/specs/2026-07-21-startup-device-validation-design.md` (`7c089a9`)
- Structured snapshot: `issue-snapshot.json`

## Implementation

- `client/startup_validation/workflow.py`
  - mandatory BOOTSTRAPPING → CONNECTING → WAITING_FOR_EMPTY → COLLECTING_BASELINE → VALIDATING → PASSED flow;
  - plain-language mappings for all requested failure states and stable public diagnostic codes;
  - gate opens only for `PASS`; retry retains audit linkage but creates a fresh device connection and validation run.
- `client/startup_validation/serial_connector.py`
  - uses the production CH340 discovery, `SerialByteTransport`, `DaoOneP4864Parser`, and observed 3079-byte/48×64 raw contract;
  - exposes only an opaque hash-derived device reference to the validation record.
- `client/app/startup_validation.py`
  - single-page Steady Health launch screen with the existing 64 px brand header, type hierarchy, color tokens, spacing, 12 px card radius, progress bar, status assets, buttons, and copy tone;
  - indeterminate connection progress and host-monotonic-derived determinate collection progress/countdown;
  - one primary recovery action on failure, plus a separate safe-exit action; no skip action;
  - asynchronous worker boundary keeps the Qt UI responsive, and creates the workbench only after a passing run.
- `client/app/packaged_entry.py`
  - replaces the package placeholder entry with the mandatory startup gate;
  - local validation has no network dependency.
- `client/app/packaging/FeetForcePlate.spec`
  - packages runtime logo and status assets from `client/app/assets/`.
- `scripts/capture_startup_validation.py`
  - deterministic capture for connection, 5-second collection, pass, failure, and long-copy states.

Implementation commit: `35c691f4d35676ee5a42895fd4b55ac2f6082a32`

## Automated verification

Primary matrix:

```text
./scripts/local-env.sh python -m pytest tests/startup_validation tests/device \
  client/tests/test_ray_114_startup_ui.py \
  client/tests/test_ray_114_packaged_gate.py \
  client/tests/test_ray_114_packaged_entry.py \
  -q --junitxml=docs/evidence/linear/RAY-114/pytest-results.xml
```

Result: **68 passed**. JUnit: `pytest-results.xml`.

Existing workbench UI compatibility:

```text
./scripts/local-env.sh python -m pytest \
  client/tests/test_ui_design_system.py \
  client/tests/test_ui_demo.py \
  client/tests/test_ui_read_models.py \
  client/tests/test_ray_101_qt_shell.py \
  client/tests/test_ray_101_controller.py \
  -q --junitxml=docs/evidence/linear/RAY-114/pytest-ui-regression-results.xml
```

Result: **27 passed**. JUnit: `pytest-ui-regression-results.xml`.

Covered automatically:

- success-state order and all requested public failure mappings;
- workbench creation only after `PASS`;
- no-device, occupied-device, and open-race handling;
- retry uses a fresh connection/run context;
- no customer-facing CheckSum, threshold, bad-point, stack, or port details;
- keyboard focus lands on the one primary recovery action;
- no skip control exists;
- 1280×720 minimum layout, long-copy wrapping, runtime assets, and package asset declaration;
- RAY-113 baseline service/parser/device regressions.

## Repeatable UI capture and visual review

Standard capture command:

```text
./scripts/local-env.sh python scripts/capture_startup_validation.py \
  --output-dir docs/evidence/linear/RAY-114/ui
```

2× Qt scale-factor capture command:

```text
QT_SCALE_FACTOR=2 ./scripts/local-env.sh python scripts/capture_startup_validation.py \
  --output-dir docs/evidence/linear/RAY-114/ui-hidpi
```

Reviewed captures:

- `ui/connecting-1440x900.png`: single-page shell, brand header, indeterminate progress, safe exit.
- `ui/collecting-1440x900.png`: 50% determinate progress and 3-second rounded-up countdown.
- `ui/passed-1440x900.png`: existing success icon, 100% progress, no action that could bypass the gate.
- `ui/failure-1440x900.png`: plain explanation, stable diagnostic number, one primary recovery action.
- `ui/long-copy-1280x720.png`: wrapped copy remains inside the reading width; action and safe exit remain visible.
- `ui-hidpi/`: the same five states rendered with `QT_SCALE_FACTOR=2`; the long-copy capture was visually inspected for clipping, spacing, and readable hierarchy.

Visual review result: no clipping or overflow observed at 1440×900 or 1280×720; progress, countdown, diagnostic number, action hierarchy, header/footer, and long Chinese copy remain legible. The page uses the existing Steady Health visual system and does not add global navigation.

## Verification boundary

Automated and local visual checks are complete. The following remain explicitly unverified:

- real DO-P4864 hardware timing and real disconnect/reconnect behavior;
- a real Windows target with CH340 driver, Windows high DPI, and screen scaling;
- manual keyboard-only and screen-reader acceptance on the target OS;
- operator usability in a clinic/elder-care workflow;
- signed/notarized packaged build and installer asset smoke test;
- RAY-115 durable log/telemetry persistence and delayed-upload integration.

Therefore RAY-114 may move to **In Review**, not Done.

## 2026-07-26 发布阻断复核

- `main.py` 现默认进入 `client.app.packaged_entry.main`，因此先经过 `MandatoryStartupGate`；回放和静态演示均须显式参数。
- 新增主入口自动测试覆盖默认正式入口与显式 replay 路径；启动、设备、协议、入口组合验证 **112 passed in 1.00s**，全量 offscreen 回归 **336 passed in 28.03s**。
- package 通过后的工作台组合根仍缺正式采集/存储/报告端口装配，不能以当前 `ScreeningWindow()` 视为已完成集成。真机、Windows 和人工验收仍未执行；RAY-114 保持 In Review。
- Commit SHA：尚未创建；本轮未暂存。

## 2026-07-31 真机空载基线与有效会话运行

在 macOS 本机、已连接的 CH340/DO-P4864 上进行一次无受试者运行。原始帧、加密分段和本地 AES 测试密钥仅保存在 `/private/tmp`，未写入仓库或本 evidence；以下为脱敏汇总。

```text
./scripts/local-env.sh python scripts/run_dop4864_runtime_acceptance.py \
  --device <connected-CH340-device> \
  --baseline-seconds 5 --capture-seconds 10 \
  --output-root /private/tmp/<acceptance-root> \
  --key-file /private/tmp/<acceptance-key> \
  --summary-output /private/tmp/<acceptance-summary>.json
```

- 汇总生成时间：`2026-07-31T07:44:19Z`；脱敏 summary SHA-256：`aa53315b4b277d44d61a555a2087be5de931f30b69c77e10a3bf2847d45b00e4`。
- 空载阶段：110 个已解码帧、5.139 秒，单元中位数最大原始计数为 3.0；满足脚本的空载门槛。
- 短时采集：208 帧，`COMPLETED`、`VALID`、`committed=true`；无重建帧。一次启动前噪声/重同步事件丢弃 1,794 字节，未产生无效帧。
- 重启等价恢复扫描：临时/密封隔离、孤儿注册、补传重排与中断暂存清理均为 0；已提交会话记录为 `CLOSED`/`VALID`，并具有 1 个派生产物。
- CheckSum 在基线和采集均有失配记录；依现行协议保持 `OBSERVE_ONLY` 审计，未作为本次有效会话的阻断条件。

此运行证明真实设备可完成一次完整空载窗口和硬件层有效会话提交；**未**通过实际 `MandatoryStartupGate` 进入工作台，亦未覆盖 Windows、高 DPI、键盘/读屏、操作员、断连/重连或签名包，故 RAY-114 保持 `In Review`，本节不对应 Linear 完成勾选。

## 2026-07-31 真机 MandatoryStartupGate 通过路径

使用新增的无受试者启动门验收命令，在相同已连接设备上以 `QT_QPA_PLATFORM=offscreen` 运行实际 `MandatoryStartupGate`。命令只记录公共状态和是否创建工作台；不保存原始帧、串口路径、凭据、受试者、筛查会话或报告。

```text
QT_QPA_PLATFORM=offscreen ./scripts/local-env.sh python \
  scripts/run_startup_gate_hardware_acceptance.py \
  --terminal-id hardware-acceptance-terminal \
  --timeout-seconds 30 \
  --summary-output /private/tmp/<startup-gate-summary>.json
```

- 汇总生成时间：`2026-07-31T07:46:57Z`；summary SHA-256：`c1dc6d81d94dfc56020af28f46844d1274267ea52adf2a6074af3fb91c1d9efa`。
- 实际观察状态：`BOOTSTRAPPING → WAITING_FOR_EMPTY → COLLECTING_BASELINE → VALIDATING → PASSED`；快速的连接状态由异步轮询采样未单独捕获。
- `workbench_created=true`，`timed_out=false`。与自动门禁测试共同证明：真机完整基线成功后才创建工作台。

本节覆盖 Linear 的“真机验证只有完整 5 秒校验通过后才能进入工作台”条目；不覆盖失败路径真机注入、Windows、高 DPI、键盘/读屏、操作员或签名包，因此 issue 仍为 `In Review`。

## 2026-07-31 当前启动自动验收矩阵

```text
QT_QPA_PLATFORM=offscreen ./scripts/local-env.sh python -m pytest -q \
  tests/startup_validation tests/device tests/spool \
  client/tests/test_ray_114_startup_ui.py \
  client/tests/test_ray_114_packaged_gate.py \
  client/tests/test_ray_114_packaged_entry.py \
  --junitxml=/private/tmp/feetforceplate-p2-startup-acceptance-20260731.xml
```

结果：`144 passed in 0.91s`；JUnit SHA-256：`c4f97abfcdd23db6b78df8005a36bf599f14ae4639059b89b9c89f2eb2ef6428`（`tests=144`、`failures=0`、`errors=0`）。覆盖成功/失败状态机、五秒窗口、真实进度语义、禁止跳过、重试新运行、公开错误文案与工作台门禁。该自动矩阵连同真机通过路径覆盖 RAY-114 的状态机自动测试条目；目标 Windows 和人工验收仍未完成。

## 2026-07-31 当前实现与 Linear 验收同步

- 当前启动/设备/可靠存储矩阵：`145 passed in 1.32s`；JUnit [`pytest-current-startup-20260731.xml`](pytest-current-startup-20260731.xml)，SHA-256 `7f7115a8282a557678899b018819bf050e357bade7b53334aa48cc575ac807b5`。
- 同一工作树全仓回归：`611 passed, 3 existing collection warnings, 9 subtests passed`；JUnit 保存在 RAY-84 收口目录，SHA-256 `dfd039c773e38b83a7819d424a800f0328063c5247c7f49c4b59d8a631b7338a`。
- 重新目视检查 `ui/connecting-1440x900.png`、`ui/collecting-1440x900.png`、`ui/failure-1440x900.png` 与 `ui-hidpi/long-copy-1280x720.png`：连接页为不确定进度；采集页显示真实 50% 与 3 秒倒计时，并明确“设备表面请勿站人、请勿放置物品”；失败页只有一个主要恢复动作、稳定编号及安全退出；2×长文案没有裁切。
- 结合真实 `MandatoryStartupGate` 通过路径（summary SHA-256 `c1dc6d81d94dfc56020af28f46844d1274267ea52adf2a6074af3fb91c1d9efa`），当前可在 Linear 勾选 18/20 条。
- 仍不勾选：`Windows 高 DPI、键盘焦点和屏幕缩放下可用`、`养老院或体检机构操作员无需技术账号或协议知识即可恢复常见错误`。这两条需要真实目标 Windows 与现场操作员人工验收，RAY-114 保持 `In Review`。
