# 子任务 B：机构客户端与本地基础报告

## 目标

在共同基线 `c0e4f38` 和既有批准架构下，实现机构端一键筛查工作流、本地基础分析与 `BASIC_READY` 报告、PDF/打印，以及可理解的错误状态。客户端只通过约定端口访问设备、存储和同步能力。

## 范围边界

- 所有权：`client/app`、`client/workflow`、`client/local_analysis`、`client/reporting`、本地 UI 与相关测试。
- 不直接操作串口、数据库私表或 HTTP。
- 不实现云端接收、云端算法或 License 后台。
- 不直接改写共享文档；必要的调整只记录为建议。
- 自动化验证与真机/人工验证分开报告。

## 阶段

| 阶段 | 状态 | 验收证据 |
|---|---|---|
| 1. 基线与契约梳理 | complete | 已阅读全部必读文档及相关模块文档，记录端口、状态机、报告与错误约束 |
| 2. 现有工程与测试基线 | complete | 已建立 `/private/tmp` 隔离环境，可运行 unittest、pytest 与 pytest-qt |
| 3. 工作流与能力门控 | complete | RAY-101/RAY-92/RAY-91/RAY-90 已提交并在 In Review；真实设备、现场协议和人工验收边界已记录 |
| 4. 本地分析与基础报告 | complete | RAY-90/RAY-85 已提交并在 In Review；离线 `BASIC_READY` 与指标门控自动测试通过 |
| 5. UI、热力图、PDF/打印与错误状态 | complete | RAY-84 已在 In Review；RAY-96 的 PDF/打印自动合同完成，实体打印与安装人工验收保留 |
| 6. 全量验证与范围审计 | in_progress | 当前 89 个自动测试通过；正在保存最终 JUnit、无越权依赖扫描和未验证边界 |
| 7. 提交本任务变更 | in_progress | 正在提交 RAY-96 所属文件和独立 evidence，逐次审计 staged 清单 |

## Linear 执行顺序

关系字段均为空；以下顺序按 Linear 优先级与实现依赖推导。一次只推进一个 issue：

1. `RAY-101`（Urgent，当前唯一 In Progress）：先建立一键筛查状态机、页面壳层、端口和错误恢复契约。
2. `RAY-92`（High）：实现受试者标识、选填档案和授权 DTO/用例，供工作流调用。
3. `RAY-91`（Medium）：固定默认筛查协议、引导/倒计时与质量门槛快照。
4. `RAY-90`（High）：实现纯函数基础指标和能力登记；虽然优先级较高，但依赖协议/门槛语义先稳定。
5. `RAY-85`（High）：基于 `RAY-90` 结果完成离线基础分析、版本化结果与 `BASIC_READY` 报告。
6. `RAY-84`（High）：基于显示模型和指标输出完成 48x64 热力图、COP/趋势检测视图。
7. `RAY-96`（Medium）：应用能力稳定后再做双平台打包、安装、升级与数据保留验证。

每个 issue 的 evidence 位于 `docs/evidence/linear/<ISSUE-ID>/README.md`；自动验证、真机和人工验收分别记录。

## 架构决策（待文档确认）

- 客户端依赖抽象端口，由其他模块提供适配器。
- 同一 `report_id` 下保留版本化报告，基础报告先行，云端完整报告后续覆盖展示但不破坏历史。
- 产品输出为健康筛查与风险提示，不给出疾病诊断。

## 错误记录

| 错误 | 尝试 | 处理 |
|---|---|---|
| 系统 Python 3.13 缺少 pytest、NumPy、Jinja2、PySide6 | 1 | 不污染同步来的根 `.venv`；改用 `/private/tmp` 隔离环境和 uv 缓存 |
| uv 默认缓存目录受沙箱限制 | 1 | 设置 `UV_CACHE_DIR=/private/tmp/feetforceplate-uv-cache` 后重试 |
| uv 离线模式按 `.python-version` 查找 Python 3.11，但本机只有 3.13 | 1 | 显式指定系统 `python3`（项目约束为 >=3.11）后重试 |
| uv 在线同步仍在下载大型 PySide6 依赖 | 1 | 已完成；隔离环境含 PySide6 6.11.1、pytest 9.1.1、pytest-qt 4.5.0、NumPy 2.5.1 |
