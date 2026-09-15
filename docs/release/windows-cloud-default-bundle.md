# Windows RAY-321 受控联调配置

R2 只允许 `integration`、HTTPS 明确端口 `:7443`、其对应 CA 和 License
验签公钥。它不是面向客户的发行包，也不会自动登录、激活、采集、创建会话或上传。

## Windows 运行前置条件（R3）

只可使用 PowerShell 7 的 `pwsh`；Windows PowerShell 5.1 不能运行本项目的
`dev.ps1`。首次在新的、干净的 Windows 工作树中操作前，先执行：

```powershell
pwsh -File .\dev.ps1 setup
```

该命令先按 `foundation-artifact.lock.json` 下载并校验私有 `techflex-cloud-foundation` wheel （需要对 `RGu0/techflex-cloud-foundation` 的访问权限），再建立项目锁定的运行环境。此后所有本指南中的 `dev.ps1` 和 Windows
启动器调用都保持使用 `pwsh`。

## 信任边界

共享同步目录中的 delivery **仅作证据副本**，其内容只能包含：

- `approval.json`：负责人签署前固定的批准 payload；
- `approval.sig`：上述文件的 Base64 Ed25519 detached signature；
- `public-cloud-defaults/` 下固定的 `cloud-default.json`、`cloud-ca.pem`、
  `license-public.key`。

客户端源码固定批准验签公钥，校验签名后才会解析批准内容。批准 payload 固定
`target_commit`、联调 endpoint/key ID 与三个资源的 SHA-256。启动还要求
`ProjectRoot` 干净且 `HEAD` 恰好等于该 `target_commit`。delivery 输入中的脚本、
manifest、README、额外文件、目录、符号链接或 Windows reparse point 都会被拒绝。
因此 `.project-context`（包括其 evidence 目录）不能直接传给
`-DeliveryDirectory`：云同步文件在 Windows 上可能带有
`FILE_ATTRIBUTE_REPARSE_POINT`，即使文件已下载也必须 fail closed。

旧的 `delivery/` 是 R1 历史证据，未带 detached signature，不能调用。`delivery-r2/`、
`delivery-r3/` 等已签名目录都是各自目标提交的历史证据，绝不可覆盖。每个新的目标提交
必须使用此前不存在的空目录，例如 `delivery-<target-commit-short>/`。

## RAY-448 受控离线签发

approval pair 只能由受保护的离线签发机生成。签发机运行已审核的
`scripts\sign_windows_cloud_delivery.py`，私钥、签发策略和审计日志均保留在本机
受保护目录，不能位于项目目录、工作树、`.project-context` 或同步盘。脚本不会扫描
密钥位置；策略显式指定私钥文件，并在签发前验证其导出的公钥恰好等于客户端源码内置的
RAY-448 trust anchor。策略、私钥和审计日志均不得复制到 delivery 或 evidence。

`D:\FeetForcePlate\protected-signer\policy.json` 只是以下命令中使用的**示例**路径；
它不是仓库、安装程序或签发脚本创建、发现或保证存在的约定位置。受保护签发机管理员必须
先在不受同步的普通本地目录中 provision 策略文件、与 RAY-448 trust anchor 匹配的原始
32-byte Ed25519 私钥，以及审计日志位置；该目录不得位于 OneDrive、仓库或
`project-context`。私钥不得发送、提交或写入 evidence。只有管理员完成该外部 provisioning
后，才将实际的策略路径显式传给 `--signer-policy`。

批准请求是 UTF-8 JSON，必须严格为：

```json
{
  "schema_version": "feetforceplate-controlled-delivery-signing-request/1",
  "approval_state": "approved",
  "approved_by": "Release owner",
  "requested_at": "2026-09-15T04:00:00Z",
  "expires_at": "2026-09-15T04:15:00Z",
  "target_commit": "40-character lowercase Git commit SHA"
}
```

签发策略也是本机文件，严格包含 `schema_version`
`feetforceplate-controlled-delivery-signer-policy/1`、`source`、`approved_by`、
`private_key_file`、`audit_log_file` 和不超过 3600 秒的
`maximum_request_ttl_seconds`。签发器拒绝未批准、非同一负责人、过期、超时、目标提交
不匹配、工作树不干净、资源不合法、密钥不可用或公钥不匹配的请求；这些请求不能产生
approval pair。成功输出只会在此前不存在的新目录中创建 `approval.json` 与
`approval.sig`。批准 payload 的联调 endpoint/key ID 和三个资源 SHA-256 均由签发器从
`--source` 直接导出，调用方不能声明或覆盖它们。

在干净的受控源码根目录中执行：

```powershell
# 此处路径仅为示例；替换为管理员已 provision 的本地策略路径。
pwsh -File .\dev.ps1 run python scripts\sign_windows_cloud_delivery.py sign `
  --request D:\controlled-input\approved-request.json `
  --signer-policy D:\FeetForcePlate\protected-signer\policy.json `
  --source D:\controlled-input\public-cloud-defaults `
  --project-root . `
  --output D:\controlled-input\approval-<target-commit-short>
```

只读审计可按目标提交查询，输出不含私钥、私钥路径或策略内容：

```powershell
# 此处路径仅为示例；替换为管理员已 provision 的本地策略路径。
pwsh -File .\dev.ps1 run python scripts\sign_windows_cloud_delivery.py audit `
  --signer-policy D:\FeetForcePlate\protected-signer\policy.json `
  --target-commit <40-character-lowercase-Git-commit-SHA>
```

若签发机、策略或其密钥尚未由管理员 provision，停止交付且不要复用旧 pair；这不是
`ValidateOnly` 或 approval verifier 的故障。完成外部 provisioning 后，对当前干净提交
重新发起批准请求。密钥轮换或撤销需要先发布更新后的客户端 trust anchor，再在新的
受保护签发机上 provision 与该 anchor 匹配的策略和密钥，并为每个当前提交重新签发。

### RAY-448 恢复步骤：在签发时确定目标提交

签发前，管理员必须在干净的 `master` 工作树中解析**当时**的精确 Git commit，并将该
40-character lowercase SHA 同时写入短时有效的批准请求、签发命令的 `--project-root` 所在
工作树和随后 Windows `ValidateOnly` 的工作树。不得把本指南中的任何规划期 SHA 当作仍然
有效的签发目标；在工作树准备和签发之间 `master` 若前进，旧请求和 pair 都必须作废并按
新的精确提交重新开始。

R6 规划时的 `bfd4f4cf68da1c63154aa2a62d11245c1ff3fbe9` 已被 PR #36 的
`ccf23afbb437b54cb60b73783dea066ffd1f5fd6` 取代；前者仅保留为历史上下文，不可用于
当前签发。管理员按如下步骤操作：

1. 在上述受保护的普通本地目录 provision policy、匹配 RAY-448 trust anchor 的 32-byte
   Ed25519 私钥和审计日志位置。policy 必须绑定签发人、私钥文件、审计日志和不超过
   3600 秒的请求有效期。
2. 在上述签发时解析出的 SHA 的干净工作树中创建短时有效且已批准的请求，并用显式传入的
   `--signer-policy` 签发新的 approval pair。
3. 将 pair 和三个 public defaults 组成严格的五文件交付树，复制到非同步、无 reparse point
   的本地 staging 目录，再运行 Windows `ValidateOnly`。
4. 仅保留脱敏 audit 结果、approval pair 的哈希和 `ValidateOnly` 结果作为 RAY-448 evidence。

旧 scope 曾在 `0124f4be…` 完成 Windows 验证，但该 pair 不能用于签发时解析出的目标
SHA。RAY-448 保持 In Progress，直到管理员完成该目标 SHA 的 Windows 验证。

## 构建并保留同步证据副本

在已完成上述 `setup`、提交干净且目标提交匹配的受控源码根目录中执行：

```powershell
pwsh -File .\dev.ps1 run python scripts\windows_cloud_default_bundle.py prepare `
  --source D:\controlled-input\public-cloud-defaults `
  --approval D:\controlled-input\approval.json `
  --approval-signature D:\controlled-input\approval.sig `
  --delivery "<new-empty-delivery-directory>" `
  --project-root .
```

将 `<new-empty-delivery-directory>` 替换为此前不存在的共享证据目录，例如
`.project-context\evidence\ray-321\windows-cloud-default-bundle\delivery-<target-commit-short>`。
成功后该目录即绑定该 `target_commit` 的交付证据，不可用于后续提交，也不可作为
Windows 启动器的 live delivery 输入。

## Windows 本地 staging

先验证 handoff ZIP 的发布 SHA-256，再从其中复制**恰好五项**到此前不存在的、
非同步的本地普通目录，例如
`D:\FeetForcePlate\delivery-<target-commit-short>\`。该路径不得位于 OneDrive、
`project-context`、工作树或任何会创建链接/重解析点的目录下。目标树必须严格为：

```text
delivery-<target-commit-short>/
  approval.json
  approval.sig
  public-cloud-defaults/
    cloud-default.json
    cloud-ca.pem
    license-public.key
```

不得复制 ZIP 的 README、scope/requirement 记录、模板、校验清单或额外文件。复制后，
目录根、`public-cloud-defaults/` 和五个文件都必须是普通本地对象，不得带 Windows
`ReparsePoint` 属性；否则停止，不得通过删除或放宽客户端检查来继续。任何新源码提交
（包括仅文档提交）都会改变 `target_commit`，必须由授权机重新签发这五项中的
`approval.json` 和 `approval.sig`。

## Windows 真机调用

只从本地、干净的 `ProjectRoot` 调用受控启动器，不运行同步目录中的任何脚本：

```powershell
pwsh -File "<ProjectRoot>\scripts\Invoke-FeetForcePlateCloudClient.ps1" `
  -DeliveryDirectory "D:\FeetForcePlate\delivery-<target-commit-short>" `
  -ProjectRoot "<ProjectRoot>" `
  -ValidateOnly
```

`-DeliveryDirectory` 必须是上一节的本地 staging 目录，不能是共享证据目录。启动器让
`dev.ps1` 只负责执行验证，并通过独立临时 JSON 文件读取启动设置，不解析 `dev.ps1`
的标准输出。移除 `-ValidateOnly` 后才启动 P-00。
