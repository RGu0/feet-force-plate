# Windows RAY-321 受控联调配置

R2 只允许 `integration`、HTTPS 明确端口 `:7443`、其对应 CA 和 License
验签公钥。它不是面向客户的发行包，也不会自动登录、激活、采集、创建会话或上传。

## Windows 运行前置条件（R3）

只可使用 PowerShell 7 的 `pwsh`；Windows PowerShell 5.1 不能运行本项目的
`dev.ps1`。首次在新的、干净的 Windows 工作树中操作前，先执行：

```powershell
pwsh -File .\dev.ps1 setup
```

该命令只建立项目锁定的运行环境。此后所有本指南中的 `dev.ps1` 和 Windows
启动器调用都保持使用 `pwsh`。

## 信任边界

同步目录仅可包含：

- `approval.json`：负责人签署前固定的批准 payload；
- `approval.sig`：上述文件的 Base64 Ed25519 detached signature；
- `public-cloud-defaults/` 下固定的 `cloud-default.json`、`cloud-ca.pem`、
  `license-public.key`。

客户端源码固定批准验签公钥，校验签名后才会解析批准内容。批准 payload 固定
`target_commit`、联调 endpoint/key ID 与三个资源的 SHA-256。启动还要求
`ProjectRoot` 干净且 `HEAD` 恰好等于该 `target_commit`。同步目录中的脚本、
manifest、README、额外文件、目录、符号链接或 Windows reparse point 都会被拒绝。

旧的 `delivery/` 是 R1 历史证据，未带 detached signature，不能调用；R2 必须使用
新的空目录，例如 `delivery-r2/`，绝不覆盖旧目录。

## 负责人签名输入

负责人使用其专用 RAY-321 Ed25519 私钥，对 UTF-8 编码的 `approval.json` 原始字节
生成 64 字节 Ed25519 签名，再把签名 Base64 编码为 `approval.sig`。私钥不得进入
项目目录、工作树、同步盘或命令记录。

payload 必须严格为：

```json
{
  "schema_version": "feetforceplate-windows-cloud-approval/2",
  "approval_state": "approved",
  "source": "License service public export",
  "approved_by": "License service owner",
  "approved_at": "2026-09-02T00:00:00Z",
  "environment": "integration",
  "target_commit": "40-character lowercase Git commit SHA",
  "config": {
    "api_base_url": "https://39.105.216.113:7443",
    "channel": "integration",
    "license_key_id": "license/1"
  },
  "files": {
    "public-cloud-defaults/cloud-default.json": "SHA-256",
    "public-cloud-defaults/cloud-ca.pem": "SHA-256",
    "public-cloud-defaults/license-public.key": "SHA-256"
  }
}
```

只有源码已提交且工作树干净后，`target_commit` 才能固定并签名。

## 创建同步目录

在已完成上述 `setup`、提交干净且目标提交匹配的受控源码根目录中执行：

```powershell
pwsh -File .\dev.ps1 run python scripts\windows_cloud_default_bundle.py prepare `
  --source D:\controlled-input\public-cloud-defaults `
  --approval D:\controlled-input\approval.json `
  --approval-signature D:\controlled-input\approval.sig `
  --delivery ".project-context\evidence\ray-321\windows-cloud-default-bundle\delivery-r2" `
  --project-root .
```

## Windows 真机调用

只从本地、干净的 `ProjectRoot` 调用受控启动器，不运行同步目录中的任何脚本：

```powershell
pwsh -File "<ProjectRoot>\scripts\Invoke-FeetForcePlateCloudClient.ps1" `
  -DeliveryDirectory "<同步目录>" `
  -ProjectRoot "<ProjectRoot>" `
  -ValidateOnly
```

启动器让 `dev.ps1` 只负责执行验证，并通过独立临时 JSON 文件读取启动设置，不解析
`dev.ps1` 的标准输出。移除 `-ValidateOnly` 后才启动 P-00。
