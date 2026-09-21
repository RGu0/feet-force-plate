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
