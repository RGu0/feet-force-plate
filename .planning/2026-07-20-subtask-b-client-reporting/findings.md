# 子任务 B 发现记录

## 初始事实

- 当前 `HEAD`：`c0e4f38113453f2c517158347b499618ce19f6f6`。
- 当前分支：`master`。
- 工作区存在未跟踪文件 `.gitignore`、`.python-version`、`AGENTS.md`、`main.py`、`pyproject.toml`、`refs/`、`uv.lock`；均不属于本任务，保持不动。
- 必读共享文档和 11 份模块文档均存在。

## 待提取

- 客户端工作流状态机与恢复规则。
- 设备、存储、同步的公开端口。
- 本地分析能力门控与基础指标。
- 报告版本、PDF/打印和错误状态契约。
- 同意/非实名建档约束。

## 模块契约摘要（第一轮）

- 客户流程固定为 `HOME -> SUBJECT_IDENTIFICATION -> CONSENT_CONFIRMATION -> PREFLIGHT -> POSITION_GUIDANCE -> ACQUIRING -> FINALIZING -> BASIC_REPORT`，完整报告异步到达；异常使用 `RETRY_REQUIRED` / `INCOMPLETE` 等显式状态。
- `ScreeningCoordinator` 是一次筛查的唯一编排者；UI 只依赖 Subject / Device / Session / Analysis / Sync / Report 端口及不可变 DTO，不持有数据库实体或文件句柄。
- 预检失败不得创建正式会话；采集中断不得拼接为成功会话；上传或云分析失败不阻断已经可用的基础报告。
- 客户端术语固定为“检测、基础报告、完整报告、重新检测”；技术细节仅进内部日志，界面展示稳定错误编号与可执行动作。
- 支持机构编号和非实名档案，平台内部仍使用 `subject_uuid`；姓名、身份证、联系方式首版不强制且不能进入算法请求、日志或对象路径。
- 授权记录不可变并带政策版本；同目的/方式/范围可复用，有实质变化必须重新确认；每次会话保存 `consent_record_id` 快照。
- 报告生命周期为 `NOT_AVAILABLE -> BASIC_READY(v1, local) -> CLOUD_ANALYZING -> FULL_READY(v2+, cloud)`；同一 `report_id` 版本化且各版本不可变。
- 本地基础报告仅包含通过能力门控的热力图、相对载荷、左右/前后分布、基础 COP 与少量批准提示，不得出现内部质量分数、未验证指标或诊断结论。
- PDF/打印要求：安全文件名、打印前确认机构编号与时间、页码/版本/生成时间/报告号、可部署中文字体，不提供二维码或公开领取链接。
- 本地分析是纯 Python/NumPy，不依赖 Qt、SQLite、HTTP 或具体分段文件；没有已验证标定时只能展示“相对载荷”。
- 本地质量门控输出 `VALID / INVALID / DEGRADED`；首版仅 `VALID` 可生成客户报告。约 12 Hz 只支持实时显示和基础静态趋势，精细步态指标默认禁用。
- 设备、会话存储、同步和纳管均由外部模块负责。客户端只能调用端口：预检读取设备/磁盘/标定/授权/同步摘要，采集生命周期调用会话端口，上传只读同步状态。
- 离线门槛（24 小时、50 次、2 GB）阻止新测试，但允许当前测试安全结束、查看既有报告与继续同步。
- 设备断线应停止并标记 `INCOMPLETE`；质量失败应重测；显示可只消费最新帧，但不能影响可靠落盘。

## 架构与 PRD 细化

- 技术栈明确为 Python 3.11+ / PySide6 / NumPy；采集端采用模块化单体与端口/适配器。
- P2 交付门槛是操作员可独立完成标准测试；基础报告在有效采集结束后 10 秒内可查看。
- 一级导航固定为工作台、检测记录、设备与支持；设置、工程参数与内部质量信息不进入普通导航。
- 标准流程支持机构编号查找，也支持跳过编号生成临时显示编号；非实名档案的全部分析字段都可跳过，缺失状态为 `UNKNOWN` 而不是阴性。
- 返回受试者需要展示脱敏编号与少量核对信息；有效授权可跳过授权页，冲突不得自动合并。
- 预检并行检查设备、存储、标定与同步门槛；正常后自动进入站位引导。自动倒计时离开有效区域需复位，手动开始也必须满足最低条件。
- 检测页只显示热力图、剩余时间、动作提示和单一停止动作；不显示同步进度，网络变化不以弹窗打断。
- 报告导出/打印必须锁定用户正在查看的不可变版本；发现新版本只提示更新，不静默切换。
- UI 基线：1440x900，最低 1280x720；正文至少 16 px，按钮高至少 48 px，点击目标至少 44x44；状态不能只靠颜色；键盘与焦点需可用。
- 产品埋点事件包含 `screening_started`、`preflight_failed`、`acquisition_completed`、`quality_retry_required`、`basic_report_ready`、`report_exported/printed`，不含身份明文。
- 自动化与人工验收需分开：状态机/端口/算法/模板可自动测；A4/中文字体/常见 Windows 打印机、真机稳定性和机构操作员可用性需要后续人工或真机验证。

## 通信与数据库契约细化

- 通用错误对象提供 `code/message/retryable/action/details`；UI 只能消费安全的通俗 `message` 与动作，敏感技术 `details` 不可透传。
- 会话状态必须拆成五个正交维度：`lifecycle_status`、`validity_status`、`upload_status`、`analysis_status`、`report_status`，不得使用单一 `completed`。
- 重要状态枚举：生命周期 `DRAFT/PREFLIGHT/ACQUIRING/FINALIZING/CLOSED`；有效性 `UNKNOWN/VALID/INVALID/INCOMPLETE/FAILED`；报告 `NOT_AVAILABLE/BASIC_READY/CLOUD_ANALYZING/FULL_READY/CLOUD_FAILED`。
- 客户端本地报告对象与会话一对一；`report_versions` 使用 `kind=BASIC/CLOUD_COMPLETE`、`document_schema_version`、不可变 `document_json`、可选 PDF 工件引用和算法来源。
- 客户端只需定义领域端口；SQLite 表、相对路径、上传任务与 HTTP 细节属于其他模块适配器，不在本任务实现。
- 受试者创建/查找与授权端口需表达机构编号上下文、脱敏摘要、冲突状态、字段缺失状态和不可变授权回执。
- `session_id` 由客户端在创建前生成；工作流侧必须保证开始和完成动作幂等，重复点击不产生第二会话或第二报告版本。
- 同步摘要提供 `last_successful_sync/pending_sessions/pending_bytes` 与门槛决策；网络错误在宽限内为非阻断，超门槛阻断新会话。
- 报告导出与打印都应记录明确的 `report_id + version`，避免状态刷新后导出不同版本；审计写入由报告端口适配器负责。
- 报告 PDF 工件与结构化文档均为不可变快照；本地版本 1 的后续修正也必须新增版本，不能改写历史。
- 端口/契约测试应覆盖：非法状态跳转、重复开始/结束、质量失败不生成报告、网络失败不改变有效性、同 `report_id` 版本演进、未批准指标门控、身份明文不出现在文档/文件名/错误信息。

## 工程基线

- 提交基线只包含文档；尚无已提交的客户端实现或测试目录。
- 根目录 `pyproject.toml`、`uv.lock`、`main.py`、`.python-version` 等均为未跟踪共享资产，可能由其他并行任务创建，本任务不修改也不提交。
- 根 `pyproject.toml` 声明 Python 3.11+、PySide6、NumPy、Jinja2、matplotlib、pytest/pytest-qt，与批准技术栈一致；本任务将把全部生产代码和测试放在 `client/` 范围内。
- 批准规范未新增与正式文档冲突的要求；再次确认只做一键流程、基础报告、端口/适配器边界、不可变报告版本与非诊断措辞。
- 由于基础指标白名单、标定与标准测试时长仍属于待验证事实，实现必须使用显式能力声明与配置输入，默认只开放不要求绝对标定的相对指标。

## Linear 执行基线（2026-07-20T08:54:41Z）

- 项目“足底压力健康筛查与分析平台”为 High / Planned；指定 7 个 issue 均属于里程碑 `P2：一键筛查`。
- `RAY-101` 为 Urgent 且已由来源任务在 2026-07-20T08:53:51Z 置为 In Progress，并已有启动评论和 evidence 路径；其余 6 个均为 Backlog。
- 所有 7 个 issue 的 `blockedBy/blocks/relatedTo` 当前为空，因此依赖顺序是本任务根据验收内容推导，不写回虚构的 Linear 关系。
- Linear 项目描述仍引用旧 commit `477f3c2`，而本任务共同基线是较新的 `c0e4f38`；产品/架构内容一致，commit 引用存在轻微陈旧但不构成范围冲突。
- `RAY-96` 涉及 Windows/macOS 安装、签名、驱动和升级人工验证；在真实平台证据齐全前最多进入 In Review。
- `RAY-84`、`RAY-96`、`RAY-101` 均包含实际 UI/安装/操作员验收；自动化完成后仍需保持 In Review，不能标 Done。

## RAY-101 实施发现

- Qt 壳层 1280x720 offscreen 截图可正常渲染中文、侧栏、表格、检测页热力图容器和报告预览容器；这是自动渲染证据，不替代目标 Windows/高 DPI/打印/操作员人工验收。
- 页面级专业内容通过稳定对象名预留：`heatmapHost`、`reportPreview`、受试者输入、预检五项、报告/设备摘要。后续 issue 可替换内容控件而无需改变页面状态机。
- 应用层已通过端口隔离设备、会话存储、本地分析、报告和遥测；边界扫描无串口、SQLite 或 HTTP 直接导入。
- `WorkflowState` 分开表达 lifecycle/validity/upload/analysis/report，网络和云分析失败不会抹掉 `VALID` 或本地基础报告引用。
- 设备启动、会话创建和报告生成异常均转换为稳定错误编号；技术细节送遥测端口，UI DTO 不含堆栈或设备路径。
