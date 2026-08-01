# RAY-90 Evidence

- Issue：`RAY-90` 经能力门控的本地基础压力/平衡指标
- URL：https://linear.app/ray-app/issue/RAY-90/经能力门控的本地基础压力平衡指标
- 初次抓取时间：2026-07-20T08:54:41Z
- 开始实现时间：2026-07-20T10:11:18Z
- 初次抓取状态：Backlog
- 当前工作流状态：Done（2026-07-31T16:34:23Z 写入并重新读取确认）
- 里程碑：P2：一键筛查
- 优先级：High
- 关系：related issue `RAY-91`；无阻塞/被阻塞关系

## 验收条目快照

- [x] 原始计数/相对热力图、总相对载荷与左右负重
- [x] COP 当前点、路径、横纵幅度、边界面积逐项登记单位和前置条件
- [x] 未验证频域、稳定性评分和参考范围不对客户开放
- [x] 每项指标记录 definition/version/required sample rate/calibration/validation/applicable protocol/duration
- [x] 质量或前置条件失败时不输出客户数值
- [x] 纯函数和固定 fixture 回归
- [x] 与独立“云端同定义”参考计算做严格容差对齐
- [x] 输出不可变 `LocalAnalysisResult`，测试确认不覆盖原始 ndarray

## 实现文件与关键决策

- `client/local_analysis/models.py`：分析上下文、标定/质量状态、不可变指标值、拒绝原因和版本化 `LocalAnalysisResult`。
- `client/local_analysis/registry.py`：指标登记表；全部条目包含定义、版本、单位、最低采样率、标定要求、时长、适用协议、验证状态和客户可见性。
- `client/local_analysis/analyzer.py`：纯 NumPy 实现；校验 `(n,48,64)` 非负有限输入，生成原始计数/相对热力图、总量、左右比例和内部 COP 指标，不修改输入。
- `client/tests/test_ray_90_*.py` 与 `client/tests/fixtures/ray_90_basic_golden.json`：固定合成 fixture、门控、确定性、原始数据不变和独立参考容差对齐。
- [golden-output.json](golden-output.json)：固定 fixture 的可审阅输出；不含真实受试者或客户数据。

关键决策：未验证标定时只输出 `relative_count`/百分比，不把计数伪装成 N、Pa 或 kg；COP 路径/幅度/面积虽可内部确定性计算，但在真实 12 Hz、标定与样本验证完成前统一标记 `NOT_CUSTOMER_VALIDATED`；频域、稳定性评分、正常范围仅登记且不可实现/不可发布；所谓 COP “面积”明确为传感器索引坐标的包围盒面积，不冒充临床椭圆面积。

## 验证命令与结果

执行时间：2026-07-20T10:15:16Z。

```bash
QT_QPA_PLATFORM=offscreen /private/tmp/feetforceplate-subtask-b-venv/bin/python \
  -m pytest client/tests -q \
  --junitxml=docs/evidence/linear/RAY-90/pytest-results.xml
```

结果：`67 passed`；包含 RAY-90 自动测试以及 RAY-101/RAY-92/RAY-91 回归。

```bash
/private/tmp/feetforceplate-subtask-b-venv/bin/python -m compileall -q \
  client/app client/workflow client/local_analysis client/tests
```

结果：通过。

```bash
! rg -n "^(import|from) (serial|sqlite3|requests|httpx|urllib|aiohttp)" \
  client/app client/workflow client/local_analysis client/reporting
```

结果：0 命中。

## 自动测试、真机与人工边界

- 已自动验证：固定 120×48×64 fixture；原始/相对热力图；总量与左右 50/50；COP (31.5, 20.0)、路径 0、幅度/包围面积；无效质量不输出热力图或客户数值；低采样率拒绝；输入数组字节值不变；本地/独立参考实现容差 `1e-9`。
- 尚未验证：真实 DO-P4864 12 bit 计数、坏点/饱和/漂移；真实标定到物理单位；真实约 12 Hz 抖动、缺帧和 30 秒协议；云端生产算法代码的双跑对齐；参考人群/临床样本；COP 客户可见性审批。
- 因此 issue 只能进入 `In Review`，不得标 `Done`；客户当前只可见非诊断性的相对总量与左右比例。

## 失败或限制

- fixture 为合成对称双点，不代表人体压力分布，也不能证明医学有效性。
- 云端容差测试使用独立公式模拟同定义参考；生产云端分析模块尚未在本任务范围内，因此仍需后续跨模块 golden 双跑。
- `total_force_newton` 已登记为需要验证物理标定且保持不可见/未实现，防止未经标定的 count 被误标为 N。

## 关联提交

- 实现与本 evidence：`174b4ee643fa6b459040d78d7cdb3e30b1cfe77d`。
- SHA 回填：`dc14550c234e0a1feeb26e079bb394e73034e61b`。

## 2026-07-31 四阶段真机采集数据本机收口

本轮重新按 Linear 的八项验收逐条核对，不把实时连机、物理标定或临床验证加入本 issue 的软件完成定义。使用 2026-07-23 已采集并去标识化的四阶段工程 fixture，在本机完成下列验证：

1. 四个阶段共 1,658 帧均通过 `analyze_local()`；每段生成 48×64 原始计数热力图与相对热力图，并输出总相对载荷、左侧和右侧相对负重。左右和在 `1e-9` 容差内为 100%。
2. COP 当前点、路径、横纵幅度与边界面积继续由版本化 registry 登记单位及采样率/时长/标定/协议前置条件。实际四阶段每段约 20.7 秒，未达到 30 秒门槛，因此客户 COP 按真实输入被稳定拒绝为 `DURATION_TOO_SHORT`，没有借回放绕开门控。
3. 频域、稳定性评分、参考范围和物理力值仍为 `UNVALIDATED`/非客户可见；真实四阶段证据中的客户指标键严格只有三个相对指标。
4. registry 测试覆盖 definition、version、unit、required sample rate、calibration、duration、protocol、validation status 与 customer visibility。
5. 无效质量、低采样率和时长不足均不输出不满足前置条件的客户数值；四阶段实测同时覆盖时长不足路径。
6. 固定 golden fixture 与四阶段真实采集 fixture 都可重复；四阶段在拒绝所有 socket 构造时双跑结果哈希一致，且输入矩阵未修改。
7. 聚焦矩阵包含生产 `PhysicalAnalysisOrchestrator` 同一公开物理输入双跑测试，所有 56 个阶段标量与本地结果按 `1e-12` 绝对容差对齐；不再使用旧的手算公式冒充云端生产对齐。
8. 输出为不可变、版本化 `LocalAnalysisResult`，原始输入保持不变。

### 新增证据

- 脱敏四阶段摘要：[`four-stage-capability-20260731.json`](four-stage-capability-20260731.json)
  - fixture SHA-256：`2495b910bbf7e4fcca0cd0db36dde809f0fd6395bb6060eded44db575acd6f90`
  - evidence SHA-256：`e67896aaaa4ac902228ab6563ce617891e6c9eb49f892038751ffe1fff11da09`
  - result SHA-256：`89c46b8ebffeab161417ceb88cd6d0d5091c2faf9a2f3c32c625f583f499be59`
  - 原始矩阵未写入 evidence。
- 聚焦 JUnit：[`pytest-four-stage-capability-20260731.xml`](pytest-four-stage-capability-20260731.xml)，`14 passed`，SHA-256 `22456bd1a0705ecaabe900fed73b2cd2089f226a169f8e09321df6dd09e86217`。
- 全仓 JUnit：[`pytest-full-four-stage-capability-20260731.xml`](pytest-full-four-stage-capability-20260731.xml)，`610 passed, 3 existing collection warnings, 9 subtests passed`，SHA-256 `dfe2d9202df7e9e14a33b8e2a9fe9052609001ea72d1f736e697f2e9bfa30908`。
- 新增生成器：`scripts/run_ray90_four_stage_evidence.py`；新增证据测试：`client/tests/test_ray_90_four_stage_evidence.py`。
- Ruff 与 `git diff --check`：通过。

### 完成边界

- 本 issue 完成的是经能力门控的本地相对指标、内部 COP 能力、元数据登记、失败关闭、固定 fixture 回归、生产云端同定义对齐和不可变结果输出。
- 不据此宣称：实时连机验收、经过批准的物理标定、COP 客户发布、参考人群/临床效度或诊断结论。
- 这些未声明能力由硬件、标定、发布门控和临床证据任务承担，不再作为 RAY-90 软件范围的隐含阻断项。
- Linear 回读：八项均为 `[X]`，证据评论 `20adfff2-e647-4bcd-960a-b2dc02428ff3` 已存在，状态为 `Done`，完成时间 `2026-07-31T16:34:23.506Z`。
