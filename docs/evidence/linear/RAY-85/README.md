# RAY-85 Evidence

- Issue：`RAY-85` 本地基础分析与断网基础报告
- URL：https://linear.app/ray-app/issue/RAY-85/本地基础分析与断网基础报告
- 初次抓取时间：2026-07-20T08:54:41Z
- 开始实现时间：2026-07-20T10:20:16Z
- 初次抓取状态：Backlog
- 当前工作流状态：In Review（2026-07-20T10:26:19Z 写入并重新读取确认）
- 里程碑：P2：一键筛查
- 优先级：High
- 关系：related issue `RAY-90`、`RAY-91`；无阻塞/被阻塞关系

## 验收条目快照

- [x] 从 CLOSED/VALID SQLite 记录和加密派生物理工件直接进入本地分析，不依赖上传；硬件原始矩阵仍按 RAY-117 边界保持私有
- [ ] 当前正式物理链已生成四阶段 COP 等内部特征，但尚未输出经客户验证的热力图、压力分布和受试者左右负重
- [ ] 物理源已要求 CLOSED/VALID，协议/阶段时长由正式特征实现校验；本地尚未完整执行云端采样率、标定版本、缺帧和发布能力门控
- [x] 输出版本化、不可变 `LocalAnalysisResult`；物理特征全部为 internal/withheld，客户指标为空
- [ ] 旧 raw-count fixture 路径可生成 BASIC_READY；当前正式物理链尚未生成客户 BASIC_READY 报告
- [ ] 本地结果可形成非权威上传快照 DTO，但尚未接入同步交接与云端物理会话重算
- [x] 去标识化真机四阶段工件在拒绝所有 socket 构造时五次完成；结果哈希一致，并记录每次耗时
- [x] 同一 `estimated-force-session/1.0` 输入逐项对齐正式 `PhysicalAnalysisOrchestrator` 的四阶段特征结果

## 实现文件与关键决策

- `client/local_analysis/service.py`：可靠会话只读端口、本地分析结果存储端口、基础报告存储端口、离线处理编排、幂等复用和非权威上传快照。
- `client/reporting/models.py`：不可变 `BasicReportDocument`、版本/状态/类型、白名单指标、相对热力图、筛查免责声明和 provenance；确定性 JSON 序列化。
- `client/tests/test_ray_85_service.py`：可靠落盘、有效/无效质量、断网独立、不可变幂等、进程重启复用、上传权威边界。
- `client/tests/test_ray_85_reporting.py`：BASIC_READY 文档序列化、无诊断声明、无内部质量/堆栈字段。
- `client/local_analysis/physical.py`：CLOSED/VALID 加密物理会话到正式四阶段纯特征实现和版本化本地结果的无网络链路。
- `client/tests/test_ray_85_physical_local.py`：真实加密提交/重开、版本边界、session identity 和正式云端编排器同输入逐项对齐。
- `scripts/run_ray85_offline_analysis_evidence.py`：用去标识化真机四阶段工件在 socket 硬失败条件下生成脱敏重复性/耗时 evidence。
- [sample-basic-report-summary.json](sample-basic-report-summary.json)：固定合成 fixture 的脱敏摘要，完整 48×64 热力图因冗长不在 evidence 摘要重复。

关键决策：processor 构造函数仅接受本地 source/store/report port 和时钟，没有上传、同步、HTTP 或云端端口；`StoredLocalAnalysis.authority=LOCAL_SUPPORTING`，上传快照固定 `SUPPORTING_NON_AUTHORITATIVE` 且 `cloud_recompute_from_raw=true`；报告 mapper 只接受 RAY-90 的 `customer_metrics`，不允许内部 COP、质量原因、频域或参考范围进入客户文档；同一 session 由报告存储端口保留 `report_id` 与下一个不可变版本。

## 验证命令与结果

执行时间：2026-07-20T10:23:59Z。

```bash
QT_QPA_PLATFORM=offscreen /private/tmp/feetforceplate-subtask-b-venv/bin/python \
  -m pytest client/tests -q \
  --junitxml=docs/evidence/linear/RAY-85/pytest-results.xml
```

结果：`73 passed`；包含 RAY-85 自动测试以及 RAY-101/RAY-92/RAY-91/RAY-90 回归。

```bash
/private/tmp/feetforceplate-subtask-b-venv/bin/python -m compileall -q \
  client/app client/workflow client/local_analysis client/reporting client/tests
```

结果：通过。

```bash
! rg -n "^(import|from) (serial|sqlite3|requests|httpx|urllib|aiohttp)" \
  client/app client/workflow client/local_analysis client/reporting
```

结果：0 命中。

## 自动测试、真机与人工边界

- 已自动验证：旧相对分析路径的有效/无效质量、BASIC_READY、白名单、幂等和非权威上传快照；新物理路径的真实加密提交/重开、本机内部结果、网络硬失败工程回放和正式云端同输入对齐；全项目回归。
- 尚未验证：正式物理热力图/受试者左右负重、完整本地采样率/标定/缺帧发布门控、正式物理 BASIC_READY、同步模块上传与云端原始重算、崩溃恢复、大量真实会话内存峰值和 COP 客户发布验证。
- 因验收 2、3、5、6 仍未完成，本 issue 只能保持 `In Review`，不得标 `Done`。

### 2026-07-31 当前架构复核

RAY-117 完成后，权威硬件到算法边界已更新为：仅整体有效且完成本地提交的会话才能导出 `estimated-force-session/1.0`，算法层只接收 points、`timestamp_s` 和 `estimated_force_n`。当前 RAY-85/RAY-90 的 `LocalAnalysisProcessor` 仍通过测试内 `_Source` 读取 48×64 count ndarray；仓库中没有 `ReliableSessionSourcePort` 的生产实现。现有 `test_local_basic_definitions_...` 也没有调用云端生产算法，而是在客户端测试内用 NumPy 重算同一公式。

本次曾以测试优先方式探测旧 raw-count 云端 `FeaturePipeline`：RED 明确证明生产模块没有这组三项基础相对指标提取；最小实现和零载荷 fail-closed 测试可以通过，且全项目达到 `595 passed`。但完成前复核确认该路径不是当前 `PhysicalAnalysisOrchestrator` 的权威 `estimated-force-session/1.0` 路径，因此相关临时代码和测试已全部撤回，未用它制造 Linear 完成证据。旧测试名称已从“independent cloud reference”纠正为“hand calculated reference”。

撤回后的当前联合验证：

```bash
QT_QPA_PLATFORM=offscreen ./scripts/local-env.sh python -m pytest -q \
  client/tests/test_ray_85_service.py \
  client/tests/test_ray_85_reporting.py \
  client/tests/test_ray_90_analysis.py \
  tests/hardware_standardization/test_public_export.py \
  tests/cloud/analysis/test_physical_features.py \
  tests/cloud/analysis/test_physical_orchestrator.py \
  tests/cloud/analysis/test_orchestrator.py \
  --junitxml=/private/tmp/feetforceplate-ray85-audit-focused-20260731.xml
```

结果：`35 passed in 0.37s`；JUnit SHA-256 `a7447ec17d90bb77d19c9e30b5905cd18ae2387fab6e2ab71a6a6a6940eb2326`。针对相关文件的 Ruff 和 `git diff --check` 均通过。

下一条正确的本地实现链必须是：已提交有效会话/加密派生工件 → 可验证重建 `estimated-force-session/1.0` → 本地物理输入分析与版本化结果 → 同一物理输入进入 `PhysicalAnalysisOrchestrator` 的容差合同。左右负重还必须结合四阶段受试者方向语义，不能直接把板面左右当作受试者左右。该语义和客户发布门控未在当前 issue 中定义，不能由旧 48×64 count 公式替代。

### 2026-07-31 已提交物理会话重开基础

以 TDD 补齐上述正确链路的第一段。RED 测试使用真实 `ValidSessionStager`、SQLite `StateStore`、AES-256-GCM 派生工件和硬件质量门，在进程持久化后调用尚不存在的读取函数，按预期因 `read_committed_physical_session` 缺失失败。最小实现随后增加：

- `client/spool/session_commit.py::read_committed_physical_session`：只接受 SQLite 中 `CLOSED/VALID` 的 session；要求恰好一个 `HARDWARE_DERIVED_OBSERVATION@hardware-derived-observation/1`；验证并解密工件；检查 session identity。
- `client/hardware_standardization/public_export.py::restore_committed_physical_pressure_session`：从已认证的硬件私有派生对象只恢复公开 `estimated-force-session/1.0` 字段，过滤 excluded cells，不向算法层暴露 raw count、相对 count、修复矩阵、source index、quality flags 或 processing metadata。
- `tests/spool/test_valid_session_commit.py::test_committed_derived_observation_reopens_as_public_physical_session`：实际提交两帧派生会话、重开并核对公开对象只有 schema/session/坐标/单位/points/frames 八类顶层字段。

验证：

```bash
QT_QPA_PLATFORM=offscreen ./scripts/local-env.sh python -m pytest -q \
  tests/spool/test_valid_session_commit.py \
  tests/hardware_standardization/test_public_export.py \
  tests/device/test_session_replay.py \
  tests/architecture/test_hardware_boundary.py \
  --junitxml=/private/tmp/feetforceplate-ray85-committed-source-focused-20260731.xml
```

结果：`16 passed in 0.41s`；JUnit SHA-256 `f9da1e19370b5fcfa305a7867d307610964b67fd85c5d40df2d5c54dc63520f7`。

```bash
QT_QPA_PLATFORM=offscreen ./scripts/local-env.sh python -m pytest -q \
  --junitxml=/private/tmp/feetforceplate-ray85-committed-source-full-20260731.xml
```

结果：`594 passed, 3 warnings, 9 subtests passed in 43.76s`；JUnit SHA-256 `a1f8555c3751a0bbf931c20c16779b3fbc387d1ea54ea4504e9864f089509c3a`。3 个 warning 仍为既有 `TestProtocol` collection warning。针对新增/相关文件的 Ruff 与 `git diff --check` 通过。

截至该 reader 增量，只完成了可靠加密存储到 RAY-117 公开物理输入的重开基础，当时尚未生成 RAY-85 本地物理指标；下一节记录后续接入后的当前状态。

### 2026-07-31 本地物理分析与四阶段离线重复性

继续按 TDD 完成正确链路的第二段：

- `client/local_analysis/physical.py::analyze_committed_physical_session` 从 CLOSED/VALID SQLite 会话和唯一加密派生工件重开公开物理输入，然后在本机直接分析；构造函数没有上传、HTTP 或云端端口。
- `analyze_physical_session` 严格解析 `estimated-force-session/1.0`，校验 session/protocol identity，并调用正式 `PhysicalAnalysisOrchestrator` 使用的同一个 `cloud.analysis.features.extract_features` 纯函数。
- 输出 `LocalAnalysisResult@result_version=1`，算法版本绑定 feature pipeline、参数版本和参数 SHA-256。四阶段共输出 56 个内部标量；没有 raw-count 热力图、客户指标或 BASIC_READY 报告，全部以 `LOCAL_PHYSICAL_FEATURE_NOT_CUSTOMER_RELEASED` withheld。
- 集成测试实际经过 `ValidSessionStager`、AES-256-GCM 派生工件、SQLite CLOSED/VALID 状态、解密重开和本地物理分析，而不是测试内 `_Source`。
- 同输入双跑测试将本地 56 个标量逐项与正式 `PhysicalAnalysisOrchestrator.handle()` 成功 run 的 feature set 以 `1e-12` 绝对容差对齐。

真实四阶段离线 evidence 使用 2026-07-23 真机采集后去标识化的 1,658 帧工程工件（SHA-256 `2495b910bbf7e4fcca0cd0db36dde809f0fd6395bb6060eded44db575acd6f90`）。运行期间 `socket.socket` 被强制拒绝构造，连续五次结果 SHA-256 均为 `3a3b1a6f53fcd5d0a73907ff11281e5dd10fbd4b32ecf6b8da7a707262d9387a`；中位耗时 `0.01225 s`，最大耗时 `0.01673 s`。见 [offline-four-stage-20260731.json](offline-four-stage-20260731.json)。该工件只保留相对矩阵，因此这里只证明工程回放的离线确定性和执行耗时，不把它冒充标定物理、客户报告、临床或当次在线真机证据。

聚焦联合验证：

```bash
QT_QPA_PLATFORM=offscreen ./scripts/local-env.sh python -m pytest -q \
  client/tests/test_ray_85_physical_local.py \
  client/tests/test_ray_85_offline_evidence.py \
  tests/spool/test_valid_session_commit.py \
  tests/hardware_standardization/test_public_export.py \
  tests/cloud/analysis/test_physical_features.py \
  tests/cloud/analysis/test_physical_orchestrator.py \
  --junitxml=docs/evidence/linear/RAY-85/pytest-physical-local-20260731.xml
```

结果：`30 passed in 0.67s`；JUnit SHA-256 `9ea57b302832fb4c877def11d6c2a09244de7bb1d90f2ed8bfa7891d342cef8d`。

全项目回归：`609 passed, 3 warnings, 9 subtests passed in 42.65s`；JUnit SHA-256 `b6cb98181c6d6fd8a5fcaa38c383b65fc72468887fff5d999a7c1a6cee681f42`。3 个 warning 仍是既有 `TestProtocol` collection warning。新增/相关文件 Ruff 和 `git diff --check` 通过。

据此仅勾选验收 1、4、7、8。验收 2、3、5、6 仍分别缺少正式物理热力图/受试者左右语义、完整本地能力门控、正式物理 BASIC_READY 报告、同步上传与云端原始重算，所以 issue 保持 `In Review`。

## 失败或限制

- 旧 `LocalAnalysisProcessor` 仍服务 raw-count BASIC fixture；正式物理链使用独立 `analyze_committed_physical_session`，尚未接入报告/同步编排。
- `sample-basic-report-summary.json` 为 evidence 摘要，不是完整导出的交付 PDF；PDF/打印由后续 reporting/packaging 工作继续验证。
- BASIC_READY 只包含非诊断性相对指标；缺少真实验证的 COP 不会因产品文案要求而绕过 RAY-90 门控。

## 关联提交

- 实现与本 evidence：`799df394d2c8b66e81d530b55301ee5df6189fa4`。
- SHA 回填：`5cd8ad58d46c5e5503ccfc55e8e2d7a8625c1deb`。
