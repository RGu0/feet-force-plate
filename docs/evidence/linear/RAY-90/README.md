# RAY-90 Evidence

- Issue：`RAY-90` 经能力门控的本地基础压力/平衡指标
- URL：https://linear.app/ray-app/issue/RAY-90/经能力门控的本地基础压力平衡指标
- 初次抓取时间：2026-07-20T08:54:41Z
- 开始实现时间：2026-07-20T10:11:18Z
- 初次抓取状态：Backlog
- 当前工作流状态：In Review（2026-07-20T10:18:01Z 写入并重新读取确认）
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
