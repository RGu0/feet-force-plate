# Windows 便携版发布放行清单

本清单用于每一次对机构交付的 Windows x86_64 便携 ZIP。任何未勾选项都意味着该 ZIP 不得交付。

## RAY-99 R5 内部验收追踪（2026-09-21）

本节记录 `windows-packaged-acceptance` scope 对 `8c354862b964ce0aa6eee7b6b3682429452dfbd4` 的内部测试，不构成客户交付放行。

| 项目 | 结果 | 受控证据 |
| --- | --- | --- |
| Windows x86_64 ZIP 完整性 | 通过；`FeetForcePlate-0.1.0-windows-x86_64.zip` SHA-256 为 `92f451a9bd87934f21b075ff393afaeca71efb01e8165da31173f8fc2c881a07` | `evidence/ray-99/windows-packaged-acceptance/acceptance/2026-09-21-r5-windows-acceptance-progress.json` |
| Windows 完整自动化验证 | 通过；`1174 passed, 28 skipped`；受限项均为 POSIX 或未配置的外部服务 | 同上 |
| 真实 CH340 强制中断与 SQLite 恢复 | 通过；中断后清理 1 个 staging 会话，正式会话、分段、产物均为 0 | 同上 |
| 实际联调服务的响应丢失恢复 | 通过；离线队列持久化，服务完成后重启不产生重复变更 | 同上 |
| 本地受控联调服务重启 | 通过；loopback TLS 服务重启后完成写入保持幂等，状态为 `INGESTED`/`VALID` | 同上 |
| 24 小时、50 会话、2 GiB 边界 | 由真实 SQLite 边界测试覆盖；到达门槛时禁止新测试，保留完成当前测试、查看历史和补传权限 | `client/tests/test_ray_99_capacity_boundaries.py` |
| 已打包 GUI 进程的四项人工验收 | 未执行；本机自动执行策略拒绝启动已构建 GUI 包，因而不能把上述源码/服务级结果表述为已打包 GUI 验收 | 同上 |

该 ZIP 的 `signing_status` 是 `unsigned-development`，只能用于内部验证。它不能填入下方的客户放行结论，也不能作为已签名机构交付包。

## RAY-99 R5 打包 GUI 真机验收进展（2026-09-23）

使用 Windows x86_64 内部候选包（源提交 `94bae58437c111e892b48900b5ae3a571cec0d7d`，ZIP SHA-256 `23a1f87ab369b11e57e930395f309a5d0ad30dbb068bf749d3a1aa766dfc7910`，`unsigned-development`）和隔离本地数据目录。操作员登录、空载准备后完成真机四段检测。SQLite 中确认 1 个 `CLOSED` / `VALID` 会话、16 个 `READY_FOR_NETWORK` 分段和 1 条持久化上传交接；重启客户端后这些本地记录仍在。

受控 WLAN 中断后已自动恢复。验收监控脚本误读 `client.sqlite3`，实际会话存于 `institution-live.sqlite3`，导致它未在离线交接出现时自动重启客户端；脚本已在本机更正，不能将此项记为通过。恢复网络后的交接处于 `BLOCKED`，最后错误码为 `E-AUT-403`，尚无云端确认。后续脱敏请求探针确认：登录刷新与 License 查询成功，令牌允许上传；云端 `create_subject` 因相同外部编号返回已有受试者（`conflict=true`），其 UUID 与本地不可变上传信封中的新 UUID 不同；队列忽略该返回值，仍以本地 UUID 创建同意记录，服务端以“受试者不属于当前租户”拒绝。不可直接把已封存的同意证据静默改绑到云端受试者。联调服务重启及其最终一致性未在本次执行。详见共享证据 `evidence/ray-99/windows-packaged-acceptance/acceptance/2026-09-23-packaged-gui-offline-restart-attempt.json`。RAY-99 的打包 GUI 验收和客户交付放行仍未完成。

## RAY-99 R6 受控恢复验收门槛

正式打包客户端应能在“设备与支持”对阻断会话展示脱敏核对信息，由已登录操作员确认同一人及新的必要处理同意，再持久化新签名同意并补传原会话。仅源代码测试通过不能替代该 Windows GUI 验收；仍须证明云端 `INGESTED/VALID`、原始分段和旧同意保留、重启恢复，以及服务重启故障注入。

## RAY-99 R7 身份核对缺口（2026-09-23）

R6 Windows 包在真实待传记录上完成了云端查询，但界面仅显示机构编号后四位。操作员明确表示无法据此确认本地与云端为同一受试者，却点击了确认。客户端随后记录了一条新授权和 `CLOUD_CONFIRMED`；这证明上传链路可达，**不构成身份核对或 RAY-99 验收通过**。客户端已关闭，原始记录和审计记录保留；该次云端会话及替代同意须由有权限的人员受控核查和处置。详见 `evidence/ray-99/windows-packaged-acceptance/acceptance/2026-09-23-r6-unverified-identity-submission.json`。

终端查询接口目前只返回云端编号掩码与非身份分析资料，云端姓名/联系方式受单独的短时授权身份访问控制。机构归属、编号后四位、年龄或性别均不能单独证明同一人。在取得双方可比对、经授权的独立身份信息及可审计核对依据前，Windows 客户端必须禁止签发替代同意和补传；该候选包不得交付。

## RAY-99 R8 受控身份恢复与隔离门槛（2026-09-24）

R8 取代上面的 R6 操作员自行勾选“同一人”流程。客户端仅展示案卷编号、状态和脱敏线索；平台授权人员须在受控边界内使用一次性短时身份访问授权，对机构原始姓名与联系方式两项进行比对。案卷同时绑定最初解析的机构编号记录及其受保护指纹，编号换绑后不得签发或消耗回执。只有服务端返回当前有效的 `MATCHED` 回执，客户端才允许本人或有权代理人重新同意必要处理与补传。算法研究同意单独选择，默认关闭。服务端在一个事务中消耗回执并登记新同意与原会话；回执拒绝后本地保留原始数据和旧授权加密审计记录，等待重新核对。

本次代码和自动化测试不证明 2026-09-23 已上传会话的身份真实性。该会话须按单独的隔离及处置案卷，由平台管理员核查后裁定；在此之前暂停后续使用。R8 放行仍须有真实 PostgreSQL 权限、迁移及事务回滚验证，Windows 便携包的受控平台比对、断网/重启后原始 16 段补传验证，以及云端最终 `INGESTED/VALID` 证据。任何一步未完成时，PR 与 RAY-99 保持未完成，不得作为客户交付包。

## 发布标识

- [ ] 应用版本：`________________`
- [ ] Git 提交：`________________`
- [ ] 构建日期与构建负责人：`________________`
- [ ] ZIP 文件名、SHA-256 与 `release-manifest.json` 已归档：`________________`
- [ ] 支持联系渠道已写入机构交付单：`________________`

## 软件包完整性

- [ ] 已通过 `scripts/verify-portable-release.ps1 -ReleaseDirectory <release-directory>`。
- [ ] `release-manifest.json` 的 `signing_status` 为 `signed`，而非 `unsigned-development`。
- [ ] `FeetForcePlate.exe` 的 Authenticode 状态为 `Valid`，证书主体、有效期与时间戳符合机构要求。
- [ ] ZIP 摘要已由独立人员复核；交付渠道使用受控下载或受控介质。
- [ ] ZIP 中包含 DO-P4864 设备规格、应用资源和支持诊断公钥（若本次交付启用诊断导出）。
- [ ] 构建机器上 `pwsh -File dev.ps1 setup` 已成功校验 `foundation-artifact.lock.json` 锁定的 `techflex-cloud-foundation` 版本与 SHA-256；本次构建未使用未校验的 wheel 或绕过 `./dev` / `dev.ps1` 的环境。
- [ ] 打包产物内的 foundation 版本与 `foundation-artifact.lock.json` 一致，并记入 `release-manifest.json`。

## 受控配置与安全

- [ ] 生产 API 地址、CA、License 公钥和机构配置由受控部署渠道提供，未提交到仓库或压缩包。
- [ ] 客户端出站敏感通信全部经由 foundation `SecureTransport` / `AuthorizedTransport`；本次构建未引入绕过它们的 HTTP 调用路径。
- [ ] 支持诊断接收方仅使用公钥；支持私钥、证书私钥、密码、令牌和真实受试者数据未进入 ZIP、清单或日志。
- [ ] License 注册、机构账户、登录与权限在目标环境已验收。
- [ ] 隐私告知、数据保留、数据删除和支持升级流程已由机构负责人确认。

## 目标机器与业务验收

- [ ] 目标 Windows x86_64 机器完成解压、签名检查、启动和退出冒烟测试。
- [ ] CH340 驱动来源和版本已确认；安装获得操作者/机构 IT 确认，未静默安装。
- [ ] 真机 DO-P4864 启动检查、连接、采集、中断恢复和重新连接已验收。
- [ ] 账号/License 与授权硬件绑定已在真实网络环境验收。
- [ ] 报告预览、PDF 导出、打印（如交付范围包含打印）和支持诊断导出已验收。
- [ ] 更新、回退、删除应用目录与保留业务数据的操作已按机构流程演练。

## 放行结论

- 发布负责人：`________________`
- 机构验收负责人：`________________`
- 放行时间：`________________`
- 结论：`[ ] 允许交付  [ ] 拒绝交付`
