# 终端数据密钥信封设计

## 决策

许可证只用于在线授权、终端注册和密钥策略获取，绝不直接作为加密
密钥或密钥推导输入。生产数据采用两套长期密钥对和每个工件独立的
随机数据密钥（DEK）：

1. **服务器密钥对**：服务器私钥只存在于服务端 KMS/HSM；终端只接收
   签名的服务器公钥、`key_id`、算法和有效期。
2. **终端密钥对**：首次注册时在终端生成；私钥不可导出并由操作系统
   安全存储保护，公钥注册到服务器。终端私钥永不上传给服务器。
3. **工件 DEK**：每份会话原始工件、派生工件或报告独立生成 32-byte
   随机 DEK，并在使用后只以密文信封形式保存。

数据本身采用 AEAD（当前为 AES-256-GCM）加密。DEK 至少包含两份信封：

```text
payload_ciphertext       = AEAD(DEK, payload, authenticated_metadata)
server_wrapped_dek       = Wrap(server_public_key, DEK)
terminal_wrapped_dek     = Wrap(terminal_public_key, DEK)
```

上传时服务器以其私钥解开 `server_wrapped_dek`，再解密数据；本地离线
恢复时终端以其不可导出的私钥解开 `terminal_wrapped_dek`。数据库和对象
存储仅保存密文、nonce、两个信封、`key_id`、算法和版本，不保存 DEK、
服务器私钥或终端私钥。

## License 与生命周期

keyset 的下发与验签权威是 foundation `TrustBundle` / `SignedTrustBundle` /
`TrustBundleVerifier`（见[总体架构设计](../架构设计文档.md) §14.1）；本项目不另行实现
签名信封、撤销列表或版本比较。对应关系：bundle 的 `signing_keys` 承载
`key_id → 公钥`，`revoked_key_ids` 承载撤销，`revision` 严格单调递增以拒绝回滚，
`policy` 承载随信任链下发的策略开关。License 状态与权益判定使用
`LicenseState` / `LicenseRecord` / `LicenseLifecycle` / `EntitlementDecision`。

1. 终端必须先通过服务器的 License 验证和终端身份验证，才可领取有效
   的服务器公钥配置（keyset）。
2. keyset 以 Ed25519 根公钥验签的 `SignedTrustBundle` 形式下发，并携带 `key_id`、用途、
   租户/终端约束、有效期和撤销策略；客户端通过 `TrustBundleVerifier.verify(...,
   minimum_revision=已安装 revision)` 校验，拒绝验签失败、revision 未增长或已过期的 keyset。
3. 新工件使用当前 keyset；旧工件保留其 `key_id`，服务端保留历史私钥
   直到相应保留期结束。撤销终端会阻止新会话和新 keyset，不静默破坏已
   封存工件的受控上传与恢复。
4. 当前本地回放调试不调用 HTTP，因而只能注入明确标记为开发用途的
   keyset；它不表示生产 License 验证、服务器密钥托管或密钥轮换已完成。

## 禁止项

- 不得以 License 字符串、安装包常量或普通无盐哈希推导数据密钥。
- 不得把终端私钥传给服务器，也不得把服务器私钥发给终端。
- 不得把长期对称根密钥写入 SQLite、配置、fixture、日志或普通文件。
- 不得以同一长期密钥直接加密所有会话/报告数据。
- 不得自行实现 keyset 的签名验证、撤销比对或 revision 比较，必须使用 foundation `TrustBundleVerifier`。

## 本地安全存储的角色

macOS Keychain/Secure Enclave、Windows CNG/DPAPI 等仅负责保存终端私钥或
不可导出的密钥句柄；它们不是自行生成、替代服务器治理的长期数据根
密钥。生产适配器必须显式处理锁定、不可用、轮换和恢复失败。

## 已知待对齐

当前代码尚未把 keyset 下发切换到 `TrustBundleVerifier`，License 状态也未使用
`LicenseState` / `LicenseLifecycle`；本节描述的是目标权威接口，不代表已完成。
收敛见 RAY-428 与[总体架构设计](../架构设计文档.md) §14.3。
