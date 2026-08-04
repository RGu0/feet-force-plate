# 销售库存与首次 License 激活 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** 生成独立的设备和 License 销售库存；客户首次激活时才创建机构账号、绑定库存项并开始 12 个月有效期。

**Architecture:** 销售库存保存在不属于任何 tenant 的 sales 表中。Platform Operations 批量创建设备资产序列号和 License 激活码 HMAC，两组不预配对。客户请求携带任一未售设备号和任一未用 License；同一激活事务锁定两行、创建既有 tenant access 实体、写入库存绑定记录、消费库存并返回签名 access session。

**Tech Stack:** Python 3.11, Pydantic 2, FastAPI, asyncpg/PostgreSQL 16, HMAC, Ed25519, pytest/httpx, uv wrapper.

## Global Constraints

- 使用 ./scripts/local-env.sh；不得创建或使用仓库内 .venv。
- 销售资产序列号是首次激活后的逻辑 hardware_id；USB 枚举仅用于连接诊断，不得把端口、VID/PID 或 USB 位置当成激活硬性条件。
- 库存 License 固定 12 个月，但库存阶段没有 tenant、账号、签名 License 或有效期。
- 数据库存储 License 激活码的 HMAC；明文只写入一次受控的 0600 交付文件，不能出现在日志、API 响应、测试或证据中。
- 保留现有 /v1/platform/tenants 和 /v1/access/activate；销售激活是新增路径。
- 库存生成和自动化测试不代表真机验收。

---

### Task 1: 契约与迁移

**Files:**
- Modify: shared/contracts/access_control.py
- Create: cloud/migrations/0005_sales_inventory_activation.sql
- Create: cloud/tests/test_sales_inventory_contracts.py
- Modify: deploy/aliyun/seed/install-seed-release.sh
- Modify: deploy/aliyun/seed/postgresql-role-grants.sql

**Interfaces:**
- 新增 AssetSerial，格式 FFP-DP4864- 加六位数字；扩展 HardwareIdentity 以接收 AssetSerial 或既有 usb-serial-<20 hex>。
- 新增 InventoryBatchCreateRequest(quantity, model=DO-P4864, license_period_months=12)。
- 新增 InventoryActivationRequest(tenant_name, account_name, password, password_confirmation, asset_serial, activation_code, client_installation_id)。
- 新增 POST /v1/platform/sales-inventory/batches 和 POST /v1/access/inventory-activate 所用响应模型。

- [ ] **Step 1: 写失败契约测试**

    def test_inventory_activation_accepts_sales_asset_serial() -> None:
        request = InventoryActivationRequest(
            tenant_name="康健中心", account_name="kangjian-01",
            password="correct-horse-battery-staple",
            password_confirmation="correct-horse-battery-staple",
            asset_serial="FFP-DP4864-000001",
            activation_code="ffp_inventory_code_1234567890",
            client_installation_id=uuid4(),
        )
        assert request.asset_serial == "FFP-DP4864-000001"

    def test_inventory_batch_is_fixed_to_twelve_months() -> None:
        assert InventoryBatchCreateRequest(quantity=10).license_period_months == 12

- [ ] **Step 2: 验证测试为红**

Run: ./scripts/local-env.sh python -m pytest cloud/tests/test_sales_inventory_contracts.py -q

Expected: 因缺少库存契约类型而失败。

- [ ] **Step 3: 实现最小契约和迁移**

定义上述 Pydantic 模型；激活请求必须验证两次密码一致。HardwareIdentity 的正则必须接受 AssetSerial 或既有 USB identity。迁移创建以下四个表：

    sales.inventory_batches(
        inventory_batch_id uuid primary key,
        model text check (model = 'DO-P4864'),
        license_period_months integer check (license_period_months = 12),
        quantity integer check (quantity between 1 and 100),
        created_at timestamptz not null
    )
    sales.device_inventory(
        device_inventory_id uuid primary key,
        inventory_batch_id uuid not null,
        asset_serial text unique not null,
        status text check (status in ('IN_STOCK','ACTIVATED')),
        activated_at timestamptz, tenant_id uuid, hardware_id uuid
    )
    sales.license_inventory(
        license_inventory_id uuid primary key,
        inventory_batch_id uuid not null,
        activation_code_hmac bytea unique not null,
        status text check (status in ('UNUSED','ACTIVATED')),
        activated_at timestamptz, tenant_id uuid, license_id uuid
    )
    sales.inventory_activations(
        inventory_activation_id uuid primary key,
        device_inventory_id uuid unique not null,
        license_inventory_id uuid unique not null,
        tenant_id uuid not null, account_id uuid not null,
        hardware_id uuid not null, license_id uuid not null,
        activated_at timestamptz not null
    )

外键、状态检查和唯一索引必须防止同一库存项二次激活。仅给 activation/platform 应用角色授予所需 sales 表权限。安装脚本必须幂等应用 0005。

- [ ] **Step 4: 验证为绿**

Run: ./scripts/local-env.sh python -m pytest cloud/tests/test_sales_inventory_contracts.py cloud/tests/test_deployment_assets.py -q

Expected: PASS.

- [ ] **Step 5: 提交**

    git add shared/contracts/access_control.py cloud/migrations/0005_sales_inventory_activation.sql cloud/tests/test_sales_inventory_contracts.py deploy/aliyun/seed/install-seed-release.sh deploy/aliyun/seed/postgresql-role-grants.sql
    git commit -m "feat: define sales inventory contracts"

### Task 2: 库存仓储与原子激活

**Files:**
- Modify: cloud/access_control/repository.py
- Modify: cloud/access_control/postgres.py
- Create: cloud/tests/test_sales_inventory_repository.py

**Interfaces:**
- 新增 InventoryBatchRecord、InventoryDeviceRecord、InventoryLicenseRecord。
- 新增 create_inventory_batch(batch_seed, created_at)。
- 新增 activate_inventory_atomically(activation_seed)，返回 ActivatedAccess。
- 任一激活必须把库存、tenant、账号、hardware、entitlement、assignment、binding、激活码、installation 和 inventory_activations 写在一个事务中。

- [ ] **Step 1: 写失败仓储测试**

    async def test_batch_contains_ten_unpaired_stock_rows() -> None:
        batch = await repository.create_inventory_batch(seed_for(10), created_at=NOW)
        assert len(await repository.inventory_devices(batch.inventory_batch_id)) == 10
        assert len(await repository.inventory_licenses(batch.inventory_batch_id)) == 10
        assert all(row.status == "IN_STOCK" for row in await repository.inventory_devices(batch.inventory_batch_id))

    async def test_activation_consumes_any_unused_device_and_license() -> None:
        activated = await repository.activate_inventory_atomically(activation_seed)
        assert activated.license.valid_from == NOW
        assert activated.license.valid_until == add_months(NOW, 12)
        assert await repository.device_inventory_status("FFP-DP4864-000001") == "ACTIVATED"

- [ ] **Step 2: 验证测试为红**

Run: ./scripts/local-env.sh python -m pytest cloud/tests/test_sales_inventory_repository.py -q

Expected: 因仓储方法不存在而失败。

- [ ] **Step 3: 实现内存和 PostgreSQL 仓储**

内存实现要保持全局资产序列号和 License HMAC 唯一。PostgreSQL 实现在 activation pool 的一个事务内对销售资产和 License 行执行 SELECT ... FOR UPDATE；状态检查通过后复用现有 tenant/account/hardware/entitlement 写入模式，并以资产序列号写入 logical hardware identity，设置 valid_from=activated_at 与 valid_until=add_months(activated_at, 12)，再更新两项库存并插入 inventory_activations。SQLSTATE 23505 映射为 AccessRepositoryConflict；不得返回或保存明文激活码。

- [ ] **Step 4: 验证为绿**

Run: ./scripts/local-env.sh python -m pytest cloud/tests/test_sales_inventory_repository.py cloud/tests/test_postgres_access_repository.py -q

Expected: PASS.

- [ ] **Step 5: 提交**

    git add cloud/access_control/repository.py cloud/access_control/postgres.py cloud/tests/test_sales_inventory_repository.py
    git commit -m "feat: persist sales inventory activation"

### Task 3: 平台入库、客户激活和受控 CLI

**Files:**
- Create: cloud/access_control/inventory_service.py
- Modify: cloud/access_control/tenant_service.py
- Modify: cloud/api/app.py
- Modify: cloud/api/seed.py
- Modify: cloud/access_control/cli.py
- Create: cloud/tests/test_sales_inventory_service.py
- Create: cloud/tests/test_sales_inventory_api.py

**Interfaces:**
- SalesInventoryService.create_batch(context, request) 仅接受 PLATFORM_OWNER 或 PLATFORM_OPERATIONS。
- TenantAuthenticationService.activate_inventory(request, source_fingerprint) 返回现有 ActivateAccountResponse。
- CLI: create-sales-inventory --quantity 10 --output /absolute/controlled/file。

- [ ] **Step 1: 写失败服务/API 测试**

    async def test_operations_creates_ten_independent_stock_records() -> None:
        result = await inventory.create_batch(operations, InventoryBatchCreateRequest(quantity=10))
        assert result.quantity == 10
        assert result.license_period_months == 12

    async def test_inventory_activation_starts_license_at_activation_time() -> None:
        response = await tenant_service.activate_inventory(request, source_fingerprint=b"test")
        assert response.signed_license.document.valid_from == NOW
        assert response.signed_license.document.valid_until == add_months(NOW, 12)

    def test_invalid_inventory_code_is_not_echoed(client: TestClient) -> None:
        response = client.post("/v1/access/inventory-activate", json=bad_payload)
        assert response.status_code == 401
        assert bad_payload["activation_code"] not in response.text

- [ ] **Step 2: 验证测试为红**

Run: ./scripts/local-env.sh python -m pytest cloud/tests/test_sales_inventory_service.py cloud/tests/test_sales_inventory_api.py -q

Expected: 缺少服务方法或 HTTP 路由。

- [ ] **Step 3: 实现服务、路由与 CLI**

服务用 secrets.token_urlsafe(32) 生成 License 码，用既有 HMAC 密钥生成摘要。资产序列号必须由仓储分配并发安全编号。平台接口只返回 batch_id、quantity、model、license_period_months 和创建时间。激活接口使用既有密码哈希、速率限制、审计、签名 License 和会话字段；认证失败只返回既有稳定安全错误。

CLI 通过 Platform 登录密码提示认证；标准输出只显示 batch_id、数量和 codes_printed=false。输出文件若已存在则失败；父目录 0700，文件 0600，内容为两个独立数组 asset_serials 和 license_codes，不输出配对行。

- [ ] **Step 4: 验证为绿**

Run: ./scripts/local-env.sh python -m pytest cloud/tests/test_sales_inventory_service.py cloud/tests/test_sales_inventory_api.py cloud/tests/test_platform_provisioning.py cloud/tests/test_tenant_authentication.py cloud/tests/test_api_tenant_isolation.py -q

Expected: PASS.

- [ ] **Step 5: 提交**

    git add cloud/access_control/inventory_service.py cloud/access_control/tenant_service.py cloud/api/app.py cloud/api/seed.py cloud/access_control/cli.py cloud/tests/test_sales_inventory_service.py cloud/tests/test_sales_inventory_api.py
    git commit -m "feat: activate sales inventory licenses"

### Task 4: 客户端首次注册输入设备资产序列号

**Files:**
- Modify: client/cloud/access_client.py
- Modify: client/app/institution_access.py
- Modify: client/tests/test_access_client.py
- Modify: client/tests/test_institution_access_ui.py

**Interfaces:**
- CloudAccessClient.activate_inventory(request) POST 到 /v1/access/inventory-activate。
- 注册界面新增 objectName 为 assetSerialInput 的设备资产序列号字段。
- 空设备号、空 License、空账号或不一致密码均不得发起网络激活。

- [ ] **Step 1: 写失败客户端/UI 测试**

    def test_access_client_posts_inventory_activation() -> None:
        result = client.activate_inventory(request)
        assert transport.requests[0].url.path == "/v1/access/inventory-activate"
        assert result.account_state is AccountState.ACTIVE

    def test_registration_does_not_activate_without_asset_serial(qtbot) -> None:
        window = InstitutionAccessWindow(on_activate_inventory=callback)
        qtbot.mouseClick(window.findChild(QPushButton, "REGISTER_INSTITUTION"), Qt.LeftButton)
        assert callback.calls == []

- [ ] **Step 2: 验证测试为红**

Run: QT_QPA_PLATFORM=offscreen ./scripts/local-env.sh python -m pytest client/tests/test_access_client.py client/tests/test_institution_access_ui.py -q

Expected: 缺少客户端方法和字段。

- [ ] **Step 3: 实现最小客户端变化**

新增 typed client 请求；注册页新增标签 设备资产序列号，样例 FFP-DP4864-000001。该字段取自设备标签，并在成功激活后成为 License 的逻辑 hardware_id；不从串口自动探测，USB 检测失败不能阻止注册。

- [ ] **Step 4: 验证为绿**

Run: QT_QPA_PLATFORM=offscreen ./scripts/local-env.sh python -m pytest client/tests/test_access_client.py client/tests/test_institution_access_ui.py client/tests/test_seed_access_runtime.py -q

Expected: PASS.

- [ ] **Step 5: 提交**

    git add client/cloud/access_client.py client/app/institution_access.py client/tests/test_access_client.py client/tests/test_institution_access_ui.py
    git commit -m "feat: register inventory licenses from client"

### Task 5: 完整验证、服务器部署与首批 10+10 库存

**Files:**
- Create: docs/evidence/linear/RAY-100/sales-inventory/README.md
- Create outside repository: /var/lib/feetforceplate/delivery/sales-inventory-<batch-id>.json

**Interfaces:**
- 服务器受控 CLI 生成数量为 10 的库存批次。
- 脱敏检查只报告 batch_id、asset_in_stock、license_unused、license_period_months、prebound_pairs 和重启后相同的计数。

- [ ] **Step 1: 跑完整受影响测试**

Run: QT_QPA_PLATFORM=offscreen ./scripts/local-env.sh python -m pytest cloud/tests client/tests -q

Expected: PASS.

- [ ] **Step 2: 部署**

根据既有 Aliyun seed 发布流程打包当前提交、应用 0005、重启 feetforceplate-seed，并用 /health/ready 确认 postgres 和 object_store 都为 ready。不得读取或输出 seed.env 值。

- [ ] **Step 3: 在服务器生成库存**

    ./scripts/local-env.sh python -m cloud.access_control.cli create-sales-inventory       --quantity 10       --output /var/lib/feetforceplate/delivery/sales-inventory-<batch-id>.json

Platform Operations 密码仅由交互提示输入。确认 stdout 不含码，交付文件归服务用户且权限为 0600。

- [ ] **Step 4: 验证服务器持久化**

在 Platform 管理上下文中仅检查：

    asset_in_stock=10
    license_unused=10
    license_period_months=12
    prebound_pairs=0

重启 PostgreSQL 和 feetforceplate-seed 后重复相同脱敏检查；计数必须相同。

- [ ] **Step 5: 写证据并提交**

证据注明库存不等于客户激活或真机验收，记录 release SHA、批次 ID、数量、0600 权限检查、重启持久化和 CH340 USB 身份限制；不得包含设备路径、License 码、密码、令牌、DSN 或原始采集数据。

    git add docs/evidence/linear/RAY-100/sales-inventory/README.md
    git commit -m "docs: record sales inventory verification"
