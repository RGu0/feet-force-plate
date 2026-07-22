# RAY-93 Evidence — 专业参数与步态分析能力门控

- Issue: RAY-93
- URL: https://linear.app/ray-app/issue/RAY-93/专业参数与步态分析能力门控
- 抓取时间: 2026-07-20T08:56:11Z
- 当时状态: In Progress（实现与自动验证完成后将同步为 In Review）
- 里程碑: P4：完整报告
- 优先级: High
- 当前状态: In Review
- 关联实现 commit SHA: `7b8ebb0ba90fbda6b062ffd845528986c37c2c73`

## 验收条目快照

- [ ] 为每个指标登记 definition、unit、algorithm_version、required_sample_rate、required_duration、calibration_requirement 和 validation_status
- [ ] 原始压力、COP、分区压力、对称性等指标按真实能力逐项验证
- [ ] 步态事件与时空参数不得沿用“要求 ≥100 Hz 但仍在 12 Hz 上输出”的旧方案
- [ ] 当前 48×64@约12 Hz 不满足门槛的指标必须隐藏或标记内部不可用
- [ ] 异常步态、停顿、不完整周期和数据质量失败进入内部门控
- [ ] 服务器预处理可以提前运行，但最终 manifest 完整前不得发布完整报告
- [ ] 算法输出可追溯到原始数据摘要、模式、标定和算法版本
- [ ] 建立离线样本集、回归测试和发布审批

## 实现文件与关键决策

- 实现：`cloud/analysis/models.py`、`cloud/analysis/features.py`、`cloud/analysis/gates.py`、`cloud/analysis/catalog.py`。
- 数据库：`cloud/analysis/migrations/0001_analysis.sql` 保存算法/管线版本、运行、特征和指标结果约束。
- 测试：`tests/cloud/analysis/test_features.py`、`tests/cloud/analysis/test_gates.py`、`tests/cloud/analysis/test_catalog.py`。
- 门控为服务器端权威规则；每项指标必须同时满足有效会话、实际采样率、标定、时长、协议/设备范围和批准状态。
- 约 12 Hz 不满足要求的步态指标只保留内部不可用状态，不进入客户报告。
- Linear 的 `INGESTED_COMPLETE` 与仓库 `session.ingested.v1` 都表示最终 manifest 已验证；不修改既有接收事件协议。

## 验证命令与逐项结果

- `python3 -m unittest tests.cloud.analysis.test_features tests.cloud.analysis.test_gates -v`
  - RED：2 个测试模块因 `cloud.analysis.features/gates` 尚不存在而按预期失败。
  - GREEN：17 个特征和能力门控测试通过。
- `python3 -m unittest tests.cloud.analysis.test_catalog -v`
  - RED：指标目录模块缺失而按预期失败。
- `python3 -m unittest discover -s tests/cloud/analysis -v`
  - GREEN：21 个测试全部通过，0 failure，0 error。
- `python3 -m compileall -q cloud/analysis tests/cloud/analysis`
  - 结果：exit 0。
- `git diff --check`
  - 结果：exit 0，无空白错误。
- Task D 最终范围验证：analysis 29、reporting 13、observability 16、migration 4，共 62 个测试通过；根目录默认 discovery 因基线没有根测试发现入口而得到 0 tests，未作为通过证据。

## 自动测试、真机与人工验证边界

- 自动测试将覆盖确定性特征、四重能力门控、约 12 Hz 拒绝高采样率指标、无效/不完整会话和发布批准。
- DO-P4864 真机采样率、标定、坏点与长期漂移未在本任务验证。
- 离线样本集的专业/临床有效性和正式算法发布审批需要外部数据与人工评审；完成前本 issue 不应标记 Done。

## 失败或限制

- 当前仓库基线没有可用的真实分段 fixture、标定资料或经批准专业指标白名单；实现只能提供默认关闭和可审计门控框架。
- evidence 不保存客户原始压力、身份字段或内部敏感诊断样本。

## 2026-07-22 V1 标准物理能力门控切片

- 实现文件：`cloud/analysis/physical_gates.py`
- 测试文件：`tests/cloud/analysis/test_physical_gates.py`
- 关键决策：
  - 仅允许 V1 静态平衡物理指标白名单；动态步态指标返回 `METRIC_NOT_IN_V1_WHITELIST`。
  - 门控只读取标准物理 schema、ML/AP、N/mm/mm²/s、测量验证版本、特征版本和质量上下文，不读取设备型号、阵列尺寸或原始计数。
  - 实际采样率、有效时长、有效帧比例、长缺口、参考工件、适配器批准和算法状态任一不满足即默认关闭。
- 自动验证：
  - `./scripts/local-env.sh python -m pytest tests/cloud/analysis/test_physical_gates.py -q` — `3 passed`
  - `./scripts/local-env.sh python -m pytest tests/cloud -q` — `104 passed, 9 subtests passed`
- 限制：合成 fixture 仅用于门控契约；18 Hz/19 s/95% 是发布门槛而非临床 cut-off，真实 RAY-117 适配器、参考工件、临床和人工审批仍未完成。
- 关联实现 commit：`80ea454`、`b654de4`。
