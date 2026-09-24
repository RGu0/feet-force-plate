# Windows 便携版发布放行清单

本清单用于每一次对机构交付的 Windows x86_64 便携 ZIP。任何未勾选项都意味着该 ZIP 不得交付。

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
- [ ] 构建机器上 `pwsh -File dev.ps1 setup` 已从公开 GitHub Release 安装 `techflex-cloud-foundation`，并按 `uv.lock` 校验锁定版本与 SHA-256；本次构建未使用未校验的 wheel 或绕过 `./dev` / `dev.ps1` 的环境。
- [ ] 打包产物内的 foundation 版本与 `pyproject.toml`、`uv.lock` 一致，并记入 `release-manifest.json`。

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

## RAY-99 身份未核实会话处置

- [ ] 平台管理员已在目标环境用 OWNER/SUPPORT 独立身份和事件工单，对确切租户与会话执行 `POST /v1/platform/tenants/{tenant_id}/sessions/{session_id}/hold`；保存脱敏的隔离状态、事件编号、请求摘要与审计引用。桌面端 `CLOUD_CONFIRMED` 不是身份核实证据。
- [ ] 确认隔离期间不会启动新分析、发布新报告或通过现有报告接口读取旧报告；原始对象和 `INGESTED` 状态仍保留。
- [ ] 隐私/服务负责人通过短时受控授权核查原始机构档案、云端身份、同意状态及已有分析/报告，再以独立工单记录处置：有可验证合法依据才可选择 `RETAIN_WITH_VALID_BASIS`；否则选择 `RESTRICT_AND_DISPOSE` 并指定本租户已批准的保留策略。
- [ ] `RESTRICT_AND_DISPOSE` 只建立 `PLANNED` 的限制任务，隔离继续生效；任务执行、数据留存/删除及撤回同意须在各自受控流程另行完成和留证。`RETAIN_WITH_VALID_BASIS` 仍需第二次明确的 `/hold/release` 操作，不能由身份匹配或新同意自动放行。
- [ ] 2026-09-23 的已上传但身份未核实会话有真实的服务器端隔离与处置审计；在此之前事件保持 open，RAY-99 不可据此通过验收或放行。

## 放行结论

- 发布负责人：`________________`
- 机构验收负责人：`________________`
- 放行时间：`________________`
- 结论：`[ ] 允许交付  [ ] 拒绝交付`
