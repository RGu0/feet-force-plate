# Windows 受控 License/cloud-default 同步包

此目录是 RAY-321 的公开客户端信任输入，只用于受控联调验收。它不是签名发行物，不得交付给客户；正式 Windows 发布、签名与升级仍按 RAY-96 执行。

## 内容和边界

`bundle-manifest.json`、`approval.json` 和 `public-cloud-defaults/` 中的三项固定文件共同定义配置。公开材料包括 HTTPS 地址、CA 证书、License 验签公钥和 key ID；目录绝不接受私钥、账号、密码、激活码、访问令牌、数据库凭据、设备标识或筛查数据。

`approval.json` 必须由 License 服务负责人以以下严格 schema 提供，且 `approval_state` 必须为 `approved`：

```json
{
  "schema_version": "feetforceplate-windows-cloud-approval/1",
  "approval_state": "approved",
  "source": "License service public export",
  "approved_by": "License service owner",
  "approved_at": "2026-08-31T00:00:00Z",
  "environment": "integration",
  "target_commit": "40-character lowercase Git commit SHA"
}
```

联调包必须使用 `integration` 与明确的 HTTPS `:7443` 端口和 CA；正式生产包必须使用 `production` 批准记录，以及标准 HTTPS 443 入口。

## 准备同步目录

在受控构建机上，从已批准的公开导出目录生成一次性同步目录。源目录只包含 `cloud-default.json`、`cloud-ca.pem` 与 `license-public.key`；批准记录由独立路径提供：

```powershell
.\dev.ps1 run python scripts\windows_cloud_default_bundle.py prepare `
  --source D:\controlled-input\public-cloud-defaults `
  --approval D:\controlled-input\approval.json `
  --delivery ".project-context\evidence\ray-321\windows-cloud-default-bundle\delivery"
```

生成器检查 HTTPS、通道、有效 CA、32 字节 Ed25519 公钥、批准记录和 SHA-256。目标目录已经存在时会停止，避免覆盖旧证据。

## Windows 真机调用

等待同步客户端显示所有文件已下载完成，再在 Windows 目标机执行。路径由参数提供，不依赖盘符、用户名或 OneDrive 根目录：

```powershell
powershell -ExecutionPolicy Bypass -File "<同步目录>\Invoke-FeetForcePlateCloudClient.ps1" `
  -DeliveryDirectory "<同步目录>" `
  -ProjectRoot "<本地 FeetForcePlate 项目目录>" `
  -ValidateOnly
```

验证成功后，移除 `-ValidateOnly` 才会启动 P-00。启动器只把公开配置传给当前进程；不会自动登录、激活、采集、创建会话或上传。任何缺失、未同步、摘要不匹配或未批准记录都会停止。

若需构建仅供内部验收的 Windows 包，先验证同步目录，再将 `FEETFORCEPLATE_CLOUD_DEFAULT_DIRECTORY` 设置为 `<同步目录>\public-cloud-defaults`，并按 `client/app/packaging/README.md` 执行受控构建。该步骤不等同于正式签名发行。
