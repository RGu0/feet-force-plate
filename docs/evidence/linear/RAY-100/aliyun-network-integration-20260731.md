# RAY-100 Aliyun 网络集成环境部署证据 — 2026-07-31

## 结论与证据边界

已在 `aliyun-agentic` 部署可从公网访问的 HTTPS **临时网络集成环境**，并通过
真实网络完成 readiness、终端激活和心跳合同验证。该环境复用仓库中的真实
FastAPI 路由和服务，不使用演示接口。

该部署不是生产环境：数据库仓储和对象存储都在进程内存中，重启会清空业务
状态并从受保护的环境文件重新播种。它不构成 PostgreSQL、OSS/S3、KMS、
生产 IAM、备份恢复、正式域名证书、生产可用性或临床就绪证据。

## 已部署的入口

- 公网入口：`https://39.105.216.113:7443`
- readiness：`GET /health/ready`
- 主机：SSH 别名 `aliyun-agentic`
- 当前发布目录：`/home/rui/apps/feetforceplate-network/releases/20260731-integration-v1`
- 当前版本软链接：`/home/rui/apps/feetforceplate-network/current`
- 受保护配置：`/home/rui/apps/feetforceplate-network/shared/integration.env`
- 启动脚本：`cloud/api/run-integration.sh`
- 重启策略：用户 crontab 的 `@reboot` + `flock`；已检查安装内容，尚未用整机
  重启验证。

主机当前监听证据：

```text
LISTEN 0 2048 0.0.0.0:7443 0.0.0.0:* users:(("python",pid=240296,fd=6))
```

重启后的内部 readiness 与获准公网探测均返回：

```json
{"status":"ready","environment":"integration","persistence":"ephemeral","object_storage":"in_memory"}
```

## TLS 与文件保护

公网读取到的证书信息：

```text
subject=CN=39.105.216.113
notBefore=Aug  1 06:42:18 2026 GMT
notAfter=Aug 31 06:42:18 2026 GMT
sha256 Fingerprint=56:FE:D0:4A:E1:87:1E:5E:E8:C5:80:B6:A2:22:F2:0C:E9:2E:3C:00:62:E0:C4:07:3E:A1:89:C5:08:F8:25:CB
```

这是 30 天自签名集成证书；客户端只能在明确导入或固定该证书后使用，不能按
生产 CA 信任链宣称。远端权限检查结果：

```text
600 rui:rui /home/rui/apps/feetforceplate-network/shared/integration.env
600 rui:rui /home/rui/apps/feetforceplate-network/shared/tls/server.key
644 rui:rui /home/rui/apps/feetforceplate-network/shared/tls/server.crt
```

证据中未保存或打印激活码、令牌密钥、HMAC 密钥、身份加密密钥或访问令牌。

## 真实公网合同验证

使用公网 HTTPS 入口执行一次终端激活，再使用返回的短期终端身份执行心跳：

```json
{
  "enroll_status": 201,
  "heartbeat_status": 200,
  "site_bound": true,
  "tenant_bound": true,
  "terminal_id_present": true
}
```

验证后已重启服务，使一次性集成激活码恢复到未消费的播种状态。重启后的进程、
监听端口和 readiness 已重新检查。

这条证据加强了 RAY-100 已勾选的“首次联网激活绑定”与“周期心跳”两项，
但不证明以下 4 个客户端/运行中边界：启动静默登录、License 安全缓存与轮换、
网络恢复自动解锁，以及实际采集进程在授权服务短暂不可达时的连续性。因此
RAY-100 仍保持 `6/10` 和 `In Review`，不标记 `Done`。

## 源码一致性与自动回归

本机与远端当前版本的 SHA-256 一致：

```text
1b46b70c5086de061bcff88bfc42e81b9dd6fb6890ceb0ab80f4f33bffd3ab44  cloud/api/integration.py
94dea389e00db9a43819187c1c8d9815188192fd21975817210841b1f608c984  cloud/api/run-integration.sh
```

全仓新鲜回归：

```text
625 passed, 3 warnings in 61.63s
```

- JUnit：`pytest-aliyun-network-deployment-20260731.xml`
- JUnit SHA-256：`673ce7ccba9df26b9263a1167d2fb334fff2c93d2e9fad250af121f5d67804ba`
- `./scripts/local-env.sh python -m compileall -q cloud/api shared client/app`：exit 0
- `git diff --check`：exit 0

三条部署专项测试覆盖：缺失服务端密钥时拒绝启动；健康接口显式披露临时存储
且不泄露密钥；真实 ASGI 组合可完成 tenant/site 绑定的激活与终端心跳。

## 仍需生产部署完成的工作

- PostgreSQL 15、迁移执行、RLS/独立 enrollment role 与并发激活审计；
- OSS/S3 持久对象存储、KMS/密钥轮换、备份恢复与保留策略；
- 正式域名、CA 证书、入口网关/WAF、限流和生产安全组；
- systemd/容器编排、监控告警、日志轮换和真实重启/故障恢复演练；
- 客户端安全凭据存储、静默登录、License 缓存/吊销和网络恢复自动解锁；
- 实际硬件采集过程中授权服务短暂不可达的连续性验证。
