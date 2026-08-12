# RAY-99 打包上传运行时与断网验收设计

**状态：** 待用户审阅

**日期：** 2026-08-11

**Linear 要求：** RAY-99 revision `R2`

**交付范围：** `packaged-upload-runtime`，随后是独立的 `lossy-network-acceptance`

## 1. 目标与结论

RAY-99 按两个已经确认的口径收口：

1. 四阶段会话只有在完整结束、质量门判定 `VALID`、原始文件完成不可变晋升后，才在同一 SQLite 事务中注册全部原始分段和持久化上传交接。`INVALID`、取消、中断及未完成会话不进入上传链。
2. 24 小时、50 次、2 GiB 门槛使用正式客户端的 SQLite、启动门禁和后台队列组合做可控边界注入，不人为等待 24 小时或实际制造 2 GiB 原始数据；随后用独立范围验证打包客户端在真实断网、慢网和进程/服务重启下的最终一致性。

首个范围不是重新实现服务端上传协议，而是把已有 `PersistentUploadQueue` 真正接入打包客户端，并补齐正式链路暴露出的身份快照、必要元数据、状态查询、重试策略、容量统计和资源生命周期缺口。

## 2. 当前事实与缺口

仓库中已经具备以下基础：

- `StateStore.commit_valid_session()` 能在一个事务中写入 `VALID` 会话、原始分段、制品和 `READY_FOR_NETWORK` 交接；
- `PersistentUploadQueue` 已实现会话创建、缺段查询、按摘要跳过已接收分段、分段 PUT 和最终清单提交；
- 服务端已提供 `GET /v1/sessions/{id}/status`，并以认证 principal 决定租户；
- `ClientAccessRuntime.current_access_token()` 已支持到期前静默刷新；
- `PackagedShutdown` 已提供打包应用的统一关闭边界。

但当前正式组合不能满足 R2：

- `PersistentUploadQueue` 和 `BackgroundAccessScheduler` 只在测试中出现，没有进入 `packaged_entry` 生产组合；
- `BackgroundAccessWorker` 要求队列实现并不存在的 `schedule_retry()`；
- 队列使用固定 30 秒重试，没有指数退避、jitter、`Retry-After` 或认证刷新分类；
- 客户端没有调用状态查询，因此“最终提交已成功但响应丢失”不能通过服务端事实快速收敛；
- 正式物理采集把上传交接的 `subject_uuid` 写成 `session_id`，云端受试者校验会拒绝该会话；
- 正式本地受试者和知情同意保存在 `InstitutionLocalStore`，上传队列既不能读取稳定快照，也不会先同步必要元数据；
- 当前本地同意记录没有持久化 `granted_at`、`evidence_type` 和终端证据签名；
- `SessionUploadContext` 把协议、载荷和标定版本做成运行时全局常量，不能证明它们属于被上传的历史会话；
- `StateStore.offline_snapshot()` 只统计旧的 `SEALED/PENDING_UPLOAD/UPLOADING/CORRUPT` 分段，漏掉正式晋升后的 `READY_FOR_NETWORK` 分段，因此 50 次和 2 GiB 门槛可能不生效；
- 服务端创建会话、受试者和同意目前使用“允许开始新测试”的 gate。License 暂停后，即使 `allow_upload=true`，尚未注册到云端的既有有效会话也无法完成必要元数据和会话注册；
- 服务端把 `terminal_id` 同时当作旧终端和 `client_installation_id`，请求契约没有 R2 明确要求的 `client_installation_id` 字段；
- 打包应用的机构库、物理 `StateStore` 和网络客户端没有统一所有权，关闭顺序也没有覆盖后台线程。

## 3. 范围与非目标

### 3.1 `packaged-upload-runtime`

本范围完成：

- 正式打包组合、启动恢复、后台线程和有序关闭；
- 会话级不可变上传快照，包括真实受试者、同意、协议/载荷/标定版本、采集时安装与硬件资产；
- 必要受试者和同意元数据的幂等同步；
- 会话创建、状态查询、缺段续传、最终确认；
- 指数退避、jitter、认证刷新和冲突/阻断分类；
- 24 小时、50 次、2 GiB 的真实 SQLite 与启动门禁边界测试；
- 源代码组合测试、API 合同测试、构建测试和可复现 evidence。

### 3.2 `lossy-network-acceptance`

第二个范围只在首个范围合并后开始，使用首个范围产出的打包客户端和联调服务完成真实断网、慢网、客户端重启、服务端重启及最终一致性证据。

### 3.3 非目标

- 不签发账号、License、激活码或硬件绑定；
- 不把 fixture、回放、源码测试或本机构建声称为真实公网、目标操作系统、实体硬件、临床或合规验收；
- 不自动删除云端已确认的本地原始数据；
- 不把客户端一级特征升级成云端权威输入；
- 不在本范围新增面向用户的“手动集中上传”操作；
- 不声称服务端已经验证客户端终端证据签名的公钥链。当前服务端只把完整同意请求纳入不可变摘要；公钥注册与验签若成为验收要求，应由 RAY-97/RAY-116 的独立修订处理。

## 4. 核心设计

### 4.1 会话级不可变上传快照

新增一个版本化的 `FormalUploadEnvelope`。它在正式采集会话建立时从认证会话、机构受试者/同意记录和本次采集冻结版本生成，至少包含：

- `schema_version`；
- `session_id`、真实 `subject_uuid`、`consent_record_id`；
- 受试者创建请求所需的最小字段；
- 同意创建请求所需的政策、用途、数据分类、授权时间、证据类型和终端证据签名；
- 采集时的 `client_installation_id` 与 `hardware_asset_id`；
- `site_id`（可空）、测试协议、应用版本、解析/协议 profile、payload schema、标定版本和配置快照；
- `started_at_ns`。

该快照使用 `SensitiveBlobCodec` 加密。`ValidSessionStager` 在最终质量门通过后，把快照与所有晋升后的分段记录一起传给 `commit_valid_session()`；SQLite migration 在 `sync_handoffs` 增加加密 `upload_envelope`。这样正式上传不依赖当前 UI 状态、当前机构库可变内容或当前硬件绑定，也不会用全局常量重写历史版本。

`LivePhysicalCapture` 必须使用 `InstitutionLiveSessions.metadata(session_id).subject_uuid`，不再把 `session_id` 代替受试者 ID。最终提交前校验 envelope、session 表和机构元数据中的 subject/consent 完全一致；不一致时本地晋升失败关闭，不产生上传交接。

### 4.2 机构受试者与同意快照

`InstitutionLocalStore` 增加只读导出边界，把加密本地记录转换为云端合同：

- 受试者：保留本地生成的 UUID；外部机构编号、可选姓名/联系方式和分析档案按现有 `SubjectCreateRequest` 映射；不上传政府证件号，因为当前云端身份合同不接收该字段；
- 同意：保留本地生成的 consent UUID，并持久化 `granted_at`、`evidence_type` 和 `terminal_signature`；复用同意时复用同一不可变快照。

生产端使用独立的 Keychain HMAC 密钥为 canonical consent evidence 生成终端证据字符串；测试注入固定 signer 与 clock。该密钥与 SQLite 加密密钥、查询 HMAC 密钥分离。服务端继续以请求摘要和幂等键防篡改/防重放；本范围不伪装成已经完成公钥注册验签。

队列按以下顺序同步：

1. 幂等创建/确认受试者；
2. 幂等创建/确认知情同意；
3. 创建/确认会话；
4. 查询会话状态；
5. 查询缺段并只上传缺失分段；
6. 提交最终清单；
7. 再次查询状态，仅在服务端返回 `validity_status=VALID` 且 `ingest_status=INGESTED` 后标记本地 `CLOUD_CONFIRMED`。

所有幂等键由对象 ID 加 canonical digest 的稳定前缀生成。服务端返回相同 ID、不同内容时进入不可自动覆盖的 `CONFLICT`。

### 4.3 认证、租户、安装和硬件语义

请求不携带可选择的 `tenant_id`。服务端始终从 tenant access token 得到 tenant/account/license/current installation 和授权能力。

`SessionCreateRequest` 新增显式 `client_installation_id`。兼容期保留 `terminal_id`，新客户端把两者都写为采集时安装 ID；若两者不一致则拒绝。数据库的历史 `terminal_id` 列继续保存该安装审计值，后续契约版本再移除 legacy 名称。

请求的 `device_id` 使用采集时认证会话中的 `hardware_asset_id`，不是 USB 端口名、CH340 枚举名或可变 `hardware_id` 文本。创建上传会话时：

- tenant 必须来自 token；
- envelope 中的采集安装和硬件资产必须属于该 tenant；
- 不要求当前存在 HardwareLease；
- 不要求采集时硬件仍是当前活跃绑定；历史有效会话的补传不能被换机、换硬件、界面锁定或 License 暂停阻断；
- 跨租户安装、硬件、受试者或同意引用全部拒绝。

会话、受试者和同意的“上传既有有效数据”路径使用 `allow_upload`，不使用 `allow_new_test`。开始新测试仍由客户端签名 License gate、24h/50/2GiB gate、启动验证和 HardwareLease 共同控制。服务端的数据上传路由不能借用 HardwareLease 作为补传前置条件。

### 4.4 打包客户端组合与资源所有权

认证成功后、启动硬件检查窗口出现前，`packaged_entry` 构造并启动 `PackagedUploadRuntime`：

```text
QApplication
  -> PackagedEntryComposition
     -> ClientAccessRuntime
     -> InstitutionLocalStore
     -> physical StateStore
     -> HttpIngestionClient
     -> PersistentUploadQueue
     -> BackgroundUploadScheduler
     -> live UI (after startup gate passes)
```

上传线程只读取已晋升、不可变文件和 SQLite handoff；串口采集、UI 和本地报告线程不等待 HTTP，不与上传线程共享可变文件句柄。界面锁定不停止 scheduler。

`PackagedShutdown` 按以下顺序关闭且保持幂等：

1. 停止并 join 后台 scheduler；
2. 关闭 HTTP client；
3. 关闭物理 `StateStore` 和机构库；
4. 关闭验证 telemetry/audit；
5. 关闭 access runtime。

`build_live_institution_runtime()` 改为接收 composition 已拥有的 store/key provider，不再自行创建同一路径的第二组连接，也不再无条件把“打开工作台”记录成联网成功。

### 4.5 启动恢复与状态机

打包上传运行时启动时先调用 `StateStore.recover_interrupted_state()`：

- `UPLOADING` 和 `RETRY_WAIT` handoff 回到可租赁状态，但保留 attempt count；
- `ACQUIRING` 会话关闭为 `INCOMPLETE`，且因为没有 valid handoff 永不上传；
- 本地原始文件不删除、不改写；
- scheduler 同一时刻只租赁一个 handoff，SQLite 状态变更在锁和事务内完成。

handoff 状态为：

```text
READY_FOR_NETWORK -> UPLOADING -> CLOUD_CONFIRMED
                         |  \
                         |   -> CONFLICT / BLOCKED
                         -> RETRY_WAIT -> UPLOADING
```

`CONFLICT` 用于本地/远端不可变摘要冲突或本地文件完整性失败；`BLOCKED` 用于不可重试合同/权限错误。两者保留本地数据并计入待传容量，不能静默覆盖或自动删除。

### 4.6 状态查询和不确定响应收敛

每次租赁 handoff 后先查询服务端状态：

- 404：尚未创建，执行必要元数据和会话注册；
- `RECEIVING`：查询分段集合，校验远端没有本地清单之外的索引，继续缺段上传；
- `INGESTED + VALID`：即使上次 complete 响应丢失，也直接本地确认；
- 远端同索引不同摘要、无效状态回退或对象身份不一致：进入 `CONFLICT`；
- 临时不可用：进入 `RETRY_WAIT`。

最终清单响应不是唯一事实来源。只有最终状态查询确认后，才更新 `CLOUD_CONFIRMED` 和最近成功联网时间。

### 4.7 退避、jitter 和错误分类

采用持久 attempt count 计算 equal-jitter：

```text
cap = min(5 seconds * 2^(attempt_count - 1), 15 minutes)
delay = cap / 2 + random(0, cap / 2)
next_attempt = now + max(delay, Retry-After)
```

clock 和随机源均可注入，测试不 sleep。

- 网络连接/读写超时、429、5xx、有效但暂未完成的状态：`RETRY_WAIT`；
- 401：强制刷新一次 access token 后重试当前安全幂等步骤；刷新失败则持久 defer，不清空队列；
- 409 或相同 ID/索引不同摘要：`CONFLICT`；
- 其他合同 4xx、跨租户/身份不匹配：`BLOCKED`；
- 本地密文、长度、路径或摘要不匹配：`CONFLICT`，不上送损坏内容。

scheduler 的轮询间隔只决定何时检查到期任务，不代替 SQLite 的 `next_attempt_at_ns`。去掉 `BackgroundAccessWorker.schedule_retry()` 的重复职责；每个已租赁 handoff 的重试状态由队列唯一负责。

### 4.8 24 小时、50 次和 2 GiB 门禁

`offline_snapshot()` 改为以 `sync_handoffs.state != CLOUD_CONFIRMED` 为待传事实，再联接其原始 segments 统计：

- pending session 数是未云确认 handoff 的 distinct session 数；
- pending bytes 是这些 handoff 的全部原始分段字节数；
- `CONFLICT`/`BLOCKED` 仍计入，防止失败数据被容量门禁忽略；
- `CLOUD_CONFIRMED` 的本地保留数据不再计入“待上传”，但仍保留到操作员显式删除。

边界语义：

- 最近成功联网时间差 `<= 24h` 允许，`> 24h` 阻止新测试；
- pending sessions `< 50` 允许，`>= 50` 阻止；
- pending bytes `< 2 GiB` 允许，`>= 2 GiB` 阻止；
- 任一门槛只改变 `allow_new_test`，始终保留 `allow_current_test_finalize`、`allow_existing_report_view` 和 `allow_upload`。

认证、状态查询或上传成功都可以更新最近成功联网时间；仅仅打开工作台、检测到 USB 设备或读取缓存不能更新。

## 5. 测试策略

### 5.1 首个范围的自动化测试

所有产品变更先写失败测试，再实现最小改动。至少覆盖：

1. **有效性边界**
   - 四阶段 `VALID` 会话在一次事务中生成真实 subject/consent 和全部 `READY_FOR_NETWORK` 分段；
   - `INVALID`、取消、中断、少一阶段、晋升失败均无 handoff；
   - 人为制造 subject/session 别名时失败关闭。
2. **必要元数据与身份**
   - 本地受试者、同意、协议和版本被快照并可在重启后恢复；
   - subject -> consent -> session 顺序与幂等键稳定；
   - token tenant 决定租户；跨租户、安装或硬件资产不匹配被拒绝；
   - 请求显式包含 `client_installation_id`、摘要和 schema/version；
   - 不上传政府证件号，客户端一级特征只作为 supporting local analysis。
3. **断点续传与状态查询**
   - 已收相同摘要跳过，不同摘要进入 conflict；
   - complete 成功但响应丢失，下一轮由 status 收敛；
   - 服务端重启后仍只补缺段；
   - 未获 `INGESTED + VALID` 不标记云确认。
4. **重试与认证**
   - equal-jitter 边界、上限和 `Retry-After`；
   - 401 强制刷新一次；429/5xx/transport defer；合同 4xx blocked；
   - License suspend 且 `allow_upload=true` 时既有 handoff 可完成必要元数据和上传；
   - 锁屏不停止上传，退出先停线程再关 store。
5. **容量门禁**
   - 24h 前、恰好 24h、超过 24h；
   - 49/50 个真实 SQLite handoff；
   - 2 GiB - 1 byte / 2 GiB 的 SQLite segment byte_count；
   - 每个阻断场景仍能运行后台队列并完成既有 handoff，确认后门禁自动恢复；
   - 测试使用小型合法文件和受控计数注入，不伪称实际传输了 2 GiB。
6. **正式组合**
   - `packaged_entry` 认证后、硬件 startup gate 前启动上传 runtime；
   - workbench 使用同一物理 store；
   - package build 包含所需模块和公开配置，不包含 secret；
   - 关闭顺序、重复关闭和启动恢复可重复验证。

自动化命令全部通过项目 manifest 的 `project_command.py --action test|build|lint` 执行，并把机器可读结果保存到 scope evidence。源码 HTTP transport、内存 repository 和可控 SQLite 测试只证明合同/组合，不证明真实公网或实体硬件。

### 5.2 第二个范围的打包与真实故障验收

`lossy-network-acceptance` 使用首个范围合并后的 commit，单独记录：

- 打包制品哈希、目标 OS、客户端版本、服务端版本和测试账号/License/硬件资产的脱敏 ID；
- 一次真实四阶段 `VALID` 会话或经明确批准的等价有效会话输入；
- 上传中真实断网再恢复；
- 分段上传中关闭并重启客户端；
- 分段或 complete 前后重启联调服务；
- 受控限速/高延迟下同时采集和生成本地基础报告，记录采集丢帧、UI 刷新和报告耗时基线/对照；
- 最终客户端状态、服务端 status、分段索引/摘要集合和 manifest 摘要一致；
- 本地文件在云确认前后均存在，只有显式操作员动作才删除。

真实公网验收要求域名、受信任 CA 和 HTTPS 443。若只能使用 IP:7443 或自签名 CA，只记录为联调证据，不标记正式公网验收完成。

## 6. 证据与完成边界

首个范围 evidence 至少包括：

- requirement revision `R2` 和 scope manifest；
- 设计与实施计划 commit；
- 红/绿测试记录、完整 test/lint/build 收据和提交 SHA；
- SQLite 边界快照及断言摘要；
- 打包组合启动/恢复/关闭的机器可读日志；
- API 请求字段与响应状态的脱敏摘要；
- 已知边界，明确未证明真实公网、慢网、进程/服务重启和实体硬件。

首个 PR 合并并完成 scope 后，才创建第二个 scope 的工作树和验收记录。第二个范围只有在打包客户端与真实故障证据齐全后才能完成。RAY-99 只有两个 scope 都合并、R2 每条验收标准逐项有证据时才可从 `In Review` 收口到 `Done`。

## 7. 实施切片

1. 修复真实 subject/consent 绑定并引入加密 `FormalUploadEnvelope`；
2. 扩展本地同意证据与受试者/同意导出合同；
3. 扩展客户端/服务端同步合同和 `client_installation_id` 交叉校验；
4. 实现 status-first 队列、错误分类和持久化 equal-jitter；
5. 修复 pending snapshot 与三个门槛的组合测试；
6. 在 `packaged_entry` 组合后台 runtime 和有序关闭；
7. 执行完整 test/lint/build、提交 scope evidence、创建 Draft PR 并进入 review；
8. 合并首个 scope 后，执行独立的打包客户端真实断网/慢网/重启验收范围。
