# RAY-102 Evidence — 云端分析流水线与版本化重算

- Issue: RAY-102
- URL: https://linear.app/ray-app/issue/RAY-102/云端分析流水线与版本化重算
- 抓取时间: 2026-07-20T08:56:11Z
- 当时状态: Backlog；2026-07-20T09:03:21Z 启动后为 In Progress
- 里程碑: P4：完整报告
- 优先级: Urgent
- 当前状态: In Review
- 关联实现 commit SHA: `7b8ebb0ba90fbda6b062ffd845528986c37c2c73`

## 验收条目快照

- [ ] INGESTED_COMPLETE 事件触发，最终清单未确认时不发布结果
- [ ] 解密/解码 → 质量评估 → 预处理 → 一级特征 → 指标/模型 → 报告数据
- [ ] 一级特征在服务端从原始数据重建
- [ ] 数据、协议、标定、特征、算法、模型和报告模式全部版本化
- [ ] 任务幂等，同一输入与版本不重复产生冲突结果
- [ ] 算法升级重算生成新版本，不覆盖既有交付
- [ ] 指标能力门控和发布审批
- [ ] 可追溯到 session manifest 与原始分段摘要
- [ ] 失败原因进入内部状态与日志，不进入客户报告
- [ ] 性能与队列扩缩容不改变结果一致性

## 实现文件与关键决策

- 实现：`cloud/analysis/models.py`、`cloud/analysis/features.py`、`cloud/analysis/gates.py`、`cloud/analysis/ports.py`、`cloud/analysis/orchestrator.py`。
- 数据库：`cloud/analysis/migrations/0001_analysis.sql`。
- 测试：`tests/cloud/analysis/test_orchestrator.py`，并回归全部 `tests/cloud/analysis`。
- 已实现 `cloud/analysis` 事件入口、版本化运行键、重算、内部失败状态、质量评估端口、原始会话加载端口和事件发布端口。
- 只消费仓库批准的 `session.ingested.v1`；Linear 的 `INGESTED_COMPLETE` 是同一已验证 manifest 门槛的业务名称。
- 不修改 `cloud/ingestion`、接收 API 或原始分段协议。

## 验证命令与逐项结果

- `python3 -m unittest tests.cloud.analysis.test_orchestrator -v`
  - RED：因 `AnalysisRunStatus`/编排模型尚不存在而按预期失败。
  - GREEN：8 个编排测试全部通过。
- `python3 -m unittest discover -s tests/cloud/analysis -v`
  - 回归：29 个 analysis 测试全部通过，0 failure，0 error。
- `python3 -m compileall -q cloud/analysis tests/cloud/analysis`
  - 结果：exit 0。
- `git diff --check`
  - 结果：exit 0，无空白错误。
- `python3 -m unittest tests.cloud.test_migrations -v`
  - 结果：4 个 Task D 迁移契约测试通过；当前环境没有 PostgreSQL，未执行真实迁移。
- Task D 最终范围验证：analysis 29、reporting 13、observability 16、migration 4，共 62 个测试通过；根目录默认 discovery 因基线没有根测试发现入口而得到 0 tests，未作为通过证据。

## 自动测试、真机与人工验证边界

- 自动测试计划覆盖事件门槛、幂等运行键、版本化重算、确定性、失败日志和身份隔离。
- PostgreSQL、对象存储、队列扩缩容、分段解密密钥和真实性能容量需要集成环境验证；完成前不应标记 Done。

## 失败或限制

- 当前基线没有 ingestion 代码、真实对象存储或队列适配器；Task D 提供显式端口与线程安全参考内存适配器。
- 真实分段解密/解码、PostgreSQL 事务、S3 对象读取、至少一次队列重复投递与峰值扩缩容仍需集成环境验证。

## 2026-07-22 V1 静态平衡算法口径同步与实施预检

- 抓取时间：2026-07-22T05:55:00Z
- 当前状态：`In Progress`
- 当前里程碑/优先级：P4：完整报告 / Urgent
- Linear URL：https://linear.app/ray-app/issue/RAY-102/云端分析流水线与版本化重算
- 关联计划 commit：`a865c6c218ed385af9fb6f2647e14150eba9f088`（主工作区的 V1 实施计划）

### 已同步的验收基线

- 云端通过 RAY-117 的 `physical-pressure-session/1.0` 重建标准物理会话；核心算法不得读取设备型号、阵列形状、行列顺序、原始计数或设备专用标定。
- 特征采用真实 N、mm、mm²、s 和受试者身体 ML/AP 坐标，覆盖 COP 路径、速度、RMS、稳健范围、95% 椭圆面积、睁闭眼变化、半串联挑战和左右前脚差异。
- `AnalysisRun` 必须纳入输入清单、硬件适配器、测量一致性、不确定度、协议、特征参数、规则、参考工件和问卷快照等不可变版本身份。
- 客户安全结果与内部质量、私有规则追踪、日志和诊断信息隔离；真实适配器、参考工件、目标环境性能与临床验证仍是 `In Review` 条件。

### 本轮实施边界

- 首个代码切片：标准物理会话消费者、严格输入校验、合成物理 fixture 和跨阵列等价性测试。
- 不修改设备解析、客户端一键流程、云端接收协议或原始分段协议。
- 旧 Task D 的 62 项自动测试仅是历史实现证据；其 48×64、设备型号、相对值和旧采样率假设不作为本版 V1 的通过结论。

### 自动验证预检

计划要求全部 Python 命令通过 `./scripts/local-env.sh` 运行。隔离工作区 `/private/tmp/feetforceplate-task-d` 当前缺少已纳入版本控制的 `pyproject.toml`、`uv.lock` 和 `scripts/local-env.sh`；它们只在主工作区以其他任务的未跟踪文件存在。

- 已执行：`ls -l pyproject.toml uv.lock scripts/local-env.sh`
  - 结果：三个文件均不存在于隔离工作区。
- 已执行：`git log --oneline --all -- pyproject.toml uv.lock scripts/local-env.sh`
  - 结果：当前可见提交历史中没有这些环境文件。

因此尚未运行 Python 测试，也没有绕过仓库规定使用系统 Python。待环境文件由其所有者提交并集成到 RAY-102 隔离分支后，按计划先写 `tests/cloud/analysis/test_physical_input.py`，观察 RED，再实现 `cloud/analysis/physical_input.py`。

### 未完成验证边界

- 自动：等待受控 uv 环境后执行；当前没有可声称的新 V1 自动测试结果。
- 真机：RAY-117/RAY-78 仍需力值、坐标、方向、时间和跨适配器证据。
- 人工/临床：冻结 60+ 参考工件、操作员一致性、PDF/打印与临床/前瞻性验证均未完成。

## 2026-07-22 标准物理输入消费者切片

- 实现文件：`cloud/analysis/physical_input.py`
- 测试文件：`tests/cloud/analysis/test_physical_input.py`
- 关键决策：
  - 只接受 `physical-pressure-session/1.0`、`SUBJECT_ML_AP`、mm/N/mm2/s；未知设备字段在边界拒绝。
  - 固定四阶段顺序、方向和左右前脚语义；每点几何和每帧力向量长度严格匹配。
  - 拒绝重复 cell、非正面积、负/非有限力、非递增时间、越界/不连续阶段和非法协议元数据。
  - 保留 `TECHNICAL_INVALID` 等业务状态供后续规则层区分，不在输入层将其解释为受试者风险。
- 自动验证：
  - `./scripts/local-env.sh python -m pytest tests/cloud/analysis/test_physical_input.py -q`
    - `19 passed`
  - `./scripts/local-env.sh python -m pytest tests/cloud -q`
    - `81 passed, 9 subtests passed`
  - `git diff --check`
    - 待本切片提交前执行。
- 验证边界：上述为合成 payload 的自动测试；尚未证明 DO-P4864 或任何真实适配器能生成通过契约的真实物理数据。RAY-117/RAY-78 真机、参考人群、目标环境性能、操作员、PDF/打印与临床验证仍未完成。

## 2026-07-22 物理特征管线切片

- 实现文件：`cloud/analysis/feature_parameters.py`、`cloud/analysis/features.py`
- 测试文件：`tests/cloud/analysis/test_physical_features.py`
- 关键决策：
  - 通过真实 N、mm、mm²、s 和身体 ML/AP 坐标计算每阶段 COP、路径、总/ML/AP 速度、RMS、P5-P95 范围、95% 椭圆、总力 CV、接触面积变化。
  - 阶段派生结果支持闭眼/睁眼、半串联/基线和左右前脚对称差异；所有比值与参数版本化。
  - 只在连续时间段内计算路径，不跨越超过两个名义间隔的时间缺口；无效帧排除但不解释为受试者风险。
  - 使用同一物理场景的四点阵列和拆分八点阵列验证结果等价；旧的设备耦合 `FeaturePipeline` 暂保留供历史回归，未作为新 V1 输入。
- 自动验证：
  - `./scripts/local-env.sh python -m pytest tests/cloud/analysis/test_physical_features.py -q`
    - `4 passed`
  - `./scripts/local-env.sh python -m pytest tests/cloud -q`
    - `85 passed, 9 subtests passed`
  - `git diff --check`
    - 提交前通过。
- 验证边界：当前参数和曲线来自合成物理 fixture；真实硬件适配器、采样能力、标定不确定度、冻结参考工件、临床/人工与 PDF 验证仍未完成。
