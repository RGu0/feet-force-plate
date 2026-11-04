# RAY-513 暂停 License 后有效会话补传设计

**状态：** 书面规格已获用户确认；R5 审批理由修订已确认

**日期：** 2026-09-23

**Linear：** RAY-513 revision R5（继承 R4，仅收窄迁移审批理由）

**交付 scope：** `suspended-valid-session-resume`

## 1. 目标与已确认边界

License 暂停须阻止新的无凭据云端 session 登记，同时不能使此前有效采集的数据丢失或无法补传。正常新客户端使用服务端预发、一次性、预绑定 session ID 的采集额度；协议上线前已采集但尚未云端登记的 `VALID` 会话，使用平台负责人核准的单会话迁移许可。两条路径均只在当前令牌 `allow_upload=true` 时允许上传；`allow_upload=false` 始终拒绝。

用户已接受以下代价：离线设备不能实时获知服务端暂停，已预发额度可在暂停后使用；额度不因上传延迟而过期，只以每安装最多 50 个未终结额度、身份绑定和一次性使用限制风险。客户端的 24 小时离线门槛继续限制本地**开始新测试**，不是云端能独立证明的采集时点。取消、无效或启动后崩溃的会话也占掉一个额度；联网且 License 有效后才可注销并补领。离线额度耗尽时只阻止新测试，不阻止历史查看、安全收尾或待传数据补传。

本设计不声称云端能从客户端时间戳、缓存签名 License、SQLite 内容或一次性额度中密码学证明采集早于暂停。旧会话人工迁移许可是有记录的例外授权，不是这样的证明。

## 2. 现状与被否决的路径

`PersistentUploadQueue` 每次尝试都先调用 `POST /v1/sessions`，然后查询缺段、上传、提交清单。PR #56 在 `IngestionService.create_session()` 入口无条件调用 `ensure_can_start_new()`；它使暂停后的裸请求得到 403，却也挡住未在云端登记的有效旧会话，以及队列的已登记会话重试。PR #56 已合并但尚未部署到 Aliyun seed，不能单独作为 R5 验收。

曾考虑的两种较简单方案均不满足目标：仅信任客户端签名 License 和自报 `started_at`，可被篡改客户端伪造；强制每次测试开始时联网登记，破坏 RAY-99 的 24 小时离线采集和长期断网后补传。采用服务端预发额度，并对无额度的历史数据设置人工审计例外。

## 3. 协议与信任边界

### 3.1 预发采集额度

机构客户端以当前 tenant access token 请求 `POST /v1/access/capture-grants`。云端仅在账号、License、硬件归属与安装绑定有效且 `allow_new_test=true` 时签发；不把当前 HardwareLease 作为额度签发或后续补传的前置条件，在线开始新测试仍沿用现有 HardwareLease 门禁。服务端在一个事务内限制同一安装未终结额度不超过 50，并为每个额度生成随机、不复用的 session UUID 与高熵不透明令牌。返回值仅包含本安装的 `(session_id, grant)`；服务端仅保存令牌摘要及 tenant、account、License、采集时硬件资产、安装、发行时间、状态和审计事件。额度与会话 UUID 在发行时就绑定，不能在使用时改绑。批量补领只补足剩余额度，不重复发行已有 grant。

服务端额度状态为 `ISSUED → CONSUMED` 或 `ISSUED → RETIRED`。仅 License 有效且在线时可将客户端确认不再使用的额度 `RETIRED`，原令牌此后永久失效；注销操作本身不删除本地无效采集或其审计。`CONSUMED` 和 `RETIRED` 不回到 `ISSUED`。没有因上传延迟触发的服务端过期时间。服务端把发行时 License 状态和绑定事实记入审计，而不是接受客户端补交的时间作为发行证明。

### 3.2 客户端占用与上传交接

客户端把额度用现有敏感数据加密边界持久化在机构本地库。现有 `InstitutionLocalStore.create_session()` 自行生成 UUID，需改为在同一个本地 SQLite 事务中选取一个 `AVAILABLE` 额度、以其预绑定 UUID 建立机构 session，并把额度标成 `ASSIGNED`；事务失败则不开始采集。由此不会出现“采集已开始但 session 尚未绑定额度”的正常路径。真实采集与本地质量门仍由现有 workflow、StateStore 和签名 License/24h/50/2GiB 门禁控制。

`VALID` 会话不可变晋升时，在 `StateStore` 的同一交接事务中保存与 session ID 绑定的加密授权引用和既有 `FormalUploadEnvelope`；队列重启后从持久化交接恢复，不从当前 UI、当前 License 文档或当前硬件绑定重建历史身份。取消、`INVALID` 或崩溃后的未完成会话把本地额度标记为已耗用，绝不分配给另一 session；联网且 License 有效时可按本地审计请求云端注销并补领。若机构库写入成功、另一 SQLite 交接未成功，恢复只允许同 session 继续或将其保留为未完成，不得回收其额度。既有有效数据无授权时保留原始数据并进入待处理状态，不静默丢弃。

### 3.3 云端首次登记与幂等重试

保持 `SessionCreateRequest` 的业务字段不变，避免把令牌混入不可变请求摘要。客户端在 `POST /v1/sessions` 的敏感请求头传一个类型可区分的不透明授权令牌和本地最终清单 SHA-256；HTTP 客户端、反向代理及诊断日志均不得记录令牌值。`Idempotency-Key` 和业务请求 canonical digest 保持稳定。已有云端 session 在 `allow_upload=true` 下，只要原 tenant/session/请求摘要匹配，即使当前 `allow_new_test=false` 也可返回幂等重试；不同摘要仍冲突。不得因重试重新消耗额度。

对尚不存在的 session，云端先检查 `allow_upload`，再按当前 `allow_new_test` 和授权类型裁定：合资格活跃请求保留原有建会话能力；暂停后的裸请求、错误 grant 或错误迁移许可均 403 且无新会话和额度副作用。正确授权必须匹配当前 tenant、授权发行时 account/License/安装/采集硬件资产、预绑定 session UUID、业务请求摘要和适用的清单摘要。当前令牌的 `allow_upload` 与历史发行事实是不同检查；若硬件或 License 后来合法更换，不要求历史硬件/License 仍是当前活跃绑定，也不能据当前绑定重写历史记录。Repository 在**同一数据库事务**内锁定授权及目标 session，核验/消耗授权并插入会话与预期清单摘要。并发双花仅一笔成功；响应丢失后同 session、同请求摘要、同清单摘要重试返回幂等结果。最终清单提交再与该预期 SHA-256 比较，拒绝不同清单。跨租户不存在性不可泄漏。

### 3.4 上线前旧会话的受控迁移

旧版 `VALID` 会话如已在云端登记，按上节已有 session 规则重试，不需要补发额度。未登记且无额度的旧会话在 License 暂停后**不自动放行**；队列保留数据和明确的“需迁移核准”状态。若 RAY-99 的受试者 UUID / 同意冲突尚未解决，必须先由操作员完成受控身份核对，取得与原 session、原 subject、云端 subject 及原 envelope 摘要绑定的持久 recovery case 和 MATCHED receipt。该 reconciliation 阶段先于首次 session registration 完成。RAY-99 当前把新 consent、最终 session 和 recovery registration 放在同一个注册事务；RAY-513 必须将授权校验/消费接入这个事务，不能让 recovery route 绕过 grant 或 legacy permit。原始上传封套与原同意保持不可变。

平台负责人核准的 RAY-513 migration permit 在身份冲突场景必须引用实际持久化的 RAY-99 case UUID，并绑定原 envelope SHA-256、原 subject UUID、最终云端 subject UUID、replacement consent ID、replacement consent canonical SHA-256、最终 `SessionCreateRequest` 摘要和最终 manifest 摘要。case 的 tenant/session/original subject/cloud subject/envelope digest 必须逐字段匹配。reference 是 UUID 外键语义，不接受自由文本。

### 3.5 RAY-99 recovery 注册与 RAY-513 授权的原子接线

RAY-99 的 case 创建及平台 MATCHED receipt 是独立且已持久化的 reconciliation 阶段；它本身不创建 session。随后 `POST /v1/identity-recovery/cases/{case_id}/register` 是可能首次创建云端 session 的入口，必须与 `POST /v1/sessions` 一样受 RAY-513 首次登记规则保护。最小接线是在既有 recovery registration 请求头接受相同的 `SessionAuthorization` 方案，并把授权验证放进 recovery repository 已有 tenant transaction；不增加中间的半注册 session，也不先提交 consent 再留下孤立 session。

授权按当前 principal 与目标 session 状态裁定：

| 情况 | 允许条件 | 持久化动作 |
|---|---|---|
| `allow_upload=false` | 一律拒绝，包括登记重放与已登记会话后续上传 | 不新增 consent/session/recovery registration，也不消费凭据 |
| 已有完全相同的 recovery registration | 当前仍 `allow_upload=true`，且相同 recovery idempotency key/request digest | 返回原回执；不再次消费 grant/permit |
| 首次登记、`allow_new_test=true` | 保留当前 active-principal 建 session 能力；若提供 grant/permit 则必须校验并消费 | consent、session、recovery registration 与所提供授权同一事务写入 |
| 首次登记、`allow_new_test=false`、有效 pre-issued grant | grant 的 tenant/account/install/hardware/session/request/manifest 全部匹配 | 同事务消费 grant 并写 consent/session/recovery registration |
| 首次登记、`allow_new_test=false`、无 grant 的旧 `VALID` 会话 | 必须有负责人签发的一次性 migration permit；身份冲突时还须命中上表所述持久 RAY-99 case | 同事务消费 permit 并写 consent/session/recovery registration |
| 暂停后的裸首次登记、无效凭据或不匹配最终 consent/subject | 一律拒绝且无副作用 | 原 envelope、同意及分段留在本地；不消费凭据 |

普通 `/v1/sessions` 和 recovery `/register` 共用相同的 authorization row/digest 校验规则。recovery 路径额外核对 RAY-99 receipt 与 case；permit 路径额外核对绑定的 reconciliation case、original envelope digest 及最终 subject/consent IDs。两种路径均先应用 `allow_upload`，然后先解决同一 session 的并发锁，再处理幂等重放与新建。新建时必须在同一事务内验证并消费授权、插入 consent/session、消费 recovery receipt、写入 `identity_recovery_registrations`；事务回滚不得留下其中任何单项副作用。`SessionCreateRequest` 保持不变，request digest 仍只由最终 session DTO 计算；replacement consent 的 canonical digest 及 RAY-99 registration digest 分别保留，manifest digest 通过现有授权头/持久列绑定。

终端先持久化不可变 `LegacyMigrationBinding`：原 envelope SHA-256、RAY-99 case UUID、原/最终 subject UUID、final consent ID 与 canonical SHA-256、最终 request/manifest digest、审批引用和加密 permit。重启重试必须重算原 envelope、replacement consent、最终 session request 与本地 manifest；任一 digest 或 UUID 不符，队列阻断且保留原始材料。未解决/过期/拒绝的 RAY-99 reconciliation 不允许发起 legacy permit 消费。若请求响应丢失，重用同一 case、receipt、session、consent、授权及 idempotency key；服务端精确重放原 registration，不能再消费 token 或创建重复 session。

### 技术审查记录（2026-09-30）

- **兼容性：** RAY-99 已把 reconciliation 分成 case 创建、平台 MATCHED receipt 与 terminal registration。前两个步骤已持久化身份关系，足以供 permit 核对；不必增加“暂存云 session”或另造 subject merge。现有 registration 仍同时创建 replacement consent/session/registration。
- **最小接线：** 扩展既有 recovery registration 入口接受 Task 1 的 `SessionAuthorization` 和 final manifest digest；新建 consent/session、RAY-99 registration/receipt 消费及 RAY-513 grant/permit 消费都留在同一个 tenant transaction。这样暂停下的无 grant 旧会话不能只凭 RAY-99 receipt 注册，且失败回滚不会留下孤立 consent 或 session。
- **状态适用性：** `allow_upload=false` 拒绝全部路径；active principal 保留原 active 首登语义，不强制所有 recovery 使用 legacy permit；已有精确 recovery registration 在 `allow_upload=true` 下只做幂等重放；paused 首登由有效 grant 放行，paused 的无 grant legacy `VALID` 必须持 owner permit。对 recovery 路径提供的 grant/permit 无论 License 当前 active 与否都必须校验，不忽略凭据。
- **原子与竞争：** PostgreSQL recovery case 创建、普通 session 创建和 recovery registration 必须共享 `recovery-session:<tenant>:<session>` advisory lock；recovery registration 的锁顺序为 session → registration idempotency key → case → receipt → session/authorization row。permit/grant 的校验/更新、会话唯一键、consent insert、receipt consume、recovery registration、授权审计均在同一事务，正确重试只返回先前结果且不二次消费。实现需确认 app-role RLS/privileges 可在该事务完成此读写。
- **摘要完整性：** session request digest 不包含 consent 内容，所以 permit 另存 replacement-consent canonical SHA-256；registration 检查 consent ID、subject ID、consent digest、request digest、manifest digest 均与 permit/binding 一致。`SessionCreateRequest` 本身不改字段。
- **客户端恢复：** queue 在 recovery registration 前验证 immutable envelope、replacement consent、final session request 与 manifest；只在所有本地绑定一致时发送授权。original envelope/consent 不回写；secret 仍仅以 `SecretStr` 传输并用现有 AES-GCM state store 加密。
- **回归矩阵：** 覆盖 active/no credential、active/credential、paused/grant、paused/permit、paused/no credential、existing replay、`allow_upload=false`、receipt/permit 过期、case/consent/session/digest 交叉错配、并发首登、丢响应重试与事务中途故障；验证全部拒绝路径无 session/consent/permit 消费副作用，且原始文件/封套摘要不变。

审查结论：该方案保留 RAY-99 的身份核对职责和 RAY-513 的暂停后首次登记授权要求，依赖现有持久 recovery case/receipt，未发现互斥的已确认 acceptance。当前 master API 未接线 authorization 属实现缺口，按本计划修复；开工前还需把 consent digest 与迁移列纳入契约/SQL/测试。

平台 `PLATFORM_OWNER` 使用独立的 `POST /v1/platform/upload-migration-permits`，提交 tenant、account、License、采集时安装/硬件、最终 session UUID、最终请求 SHA-256、最终清单 SHA-256、证据引用，以及固定的非敏感审批理由代码 `LEGACY_VALID_SESSION_REVIEWED`；接口拒绝自由文本理由。详细审批说明只保存在受限证据中，`evidence_reference` 仅是没有敏感内容的引用。审批材料须包括本地 `VALID`/不可变分段与原同意，并核对可取得的采集时授权证据（例如保留的签名 License 版本或服务端历史发行审计）；证据不足时不能自动核准。服务器在许可记录和审计中保存审批者、固定理由代码、证据引用与摘要，不复制详细说明、原始数据或敏感凭据。仅负责人可签发，签发本身及拒绝留审计。许可是高熵、一次性、仅供该 session 与两个摘要使用的不透明令牌；消费与云端新建 session 在同一事务。负责人核准代表明确的风险承担，不应在产品或证据中描述成自动验证了真实采集时刻。

旧客户端不带 grant 时，在 License 仍有效下可以按现行权限上传；若其未登记会话遇到暂停，则走上述人工路径。不能以全租户开关、无期限通用豁免或手工直接写数据库绕过。许可证恢复为 active 后，普通上传可重试，历史原始数据始终保留。

## 4. 失败、安全与可观测性

未领到额度或离线额度耗尽：新测试预检明确失败；后台上传、历史查看不受影响。授权不匹配、已注销、跨 session/安装/租户、许可摘要不符：403 或既有幂等冲突码，拒绝前不写入 session；客户端把该交接标记为需人工处理，保留原始分段和不可变封套，不能无限自动重试权限错误。网络/5xx：沿用 Foundation `RetryPolicy`；不得因响应丢失重新选择额度或生成新 session ID。进程重启：恢复本地 ASSIGNED 与 `READY_FOR_NETWORK` 状态，继续同一授权与幂等键。`allow_upload=false`：包括已登记 session 的查询、分段与清单提交均受现行授权拒绝，不借 grant 越权。

诊断事件只记录 grant/permit 的非可用标识摘要、session ID、裁定类别、审批者身份与证据引用；不记录令牌、签名 License、密码、原始分段或可复用的授权头。授权表、平台审批记录与 session 表须能追溯发行、注销、消费及对应的请求/清单摘要。现有服务端并不独立证明本地 `VALID` 质量门或离线时钟；这一限制在验收证据中保留。

## 5. 验证与发布顺序

1. 合同/数据库/服务测试：活跃发行及上限、暂停不能发行、裸请求 403 且无副作用、跨租户/安装/硬件/会话/摘要拒绝、注销后拒绝、并发消费唯一、丢响应后同会话幂等、已有会话无新 grant 重试、`allow_upload=false` 硬拒绝、最终清单摘要匹配。
2. 客户端组合测试：正式 workflow 从预发 UUID 创建本地会话；有效会话晋升与授权交接原子；取消/无效/崩溃烧掉额度；24 小时、50 次、2 GiB 本地门槛；进程重启/网络恢复/长期延迟上传；额度耗尽只挡新测；权限错误保留原始数据。覆盖真实 `PersistentUploadQueue`，不以直接 `put_segment`/`complete_session` 单测替代。
3. 人工迁移及 recovery 组合测试：暂停后无额度裸登记自动拒绝；审批需负责人身份、固定理由和证据引用；冲突场景 permit 必须引用已持久 MATCHED RAY-99 case，并匹配原 envelope、原/最终 subject、final consent ID、最终请求与清单摘要；recovery registration 首建会话须原子消费 permit，不能只靠 MATCHED receipt 越过 RAY-513；active recovery 不被强制要求 legacy permit；有效 grant 可在暂停后授权 recovery 首登；已有完全相同 registration 在 `allow_upload=true` 下精确幂等且不二次消费；`allow_upload=false` 包括重放在内全部拒绝；错误 consent、旧 digest、过期 receipt 和跨 case reference 无副作用；响应丢失/重启不重复建会话；拒批与失联不删除原始数据。测试使用脱敏 fixture，不把本机测试说成 Windows 真机验收。
4. 受管测试、lint/build、跨平台 CI、PR head 自审与证据齐全后合并本 scope。Aliyun 先发布包含 R5 修正的**精确提交**，再与 RAY-120 D10 候选明确集成；不得只部署 PR #56 或直接把当前 `master` 当成 D10 候选。受控 seed 验证暂停后裸请求 403、持合法额度的有效会话首次登记/补传、同会话重试及人工许可拒绝/通过路径，然后重跑 RAY-120 live acceptance。部署、审计与证据不得打印密钥或令牌。

此设计 scope 的 PR 不能仅因 CI 通过就标记 RAY-513 Done；须按 R5 证据与合并状态重验旧 `license-new-session-gate` 和新 scope，再核对 RAY-120 的父级验收门槛。

## 6. 文档同步与非目标

实现 scope 中同步仓库 `docs/产品需求文档_PRD.md`、`docs/modules/05-sync-upload.md`、`docs/modules/08-subject-consent.md`、本仓库旧 RAY-99 上传设计及共享上下文对应副本；逐项检查通信接口、架构文档并记录改动或不变理由。该设计文档承载 R5 当前方案，不改写 PR #56 或 RAY-99 历史证据。

非目标：改动 RAY-120 D10 identity loader、重做 credential vault、把客户端时间戳升级为可信时间证明、静默合并受试者/同意、绕过真实 Windows 打包客户端或阿里云验收。新的授权凭据只使用现有敏感数据加密及受限日志边界，不引入另一套通用凭据平台。
