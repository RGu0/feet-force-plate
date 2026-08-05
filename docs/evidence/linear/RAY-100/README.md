# RAY-100 Evidence — 终端激活纳管、联网门槛与本地功能开关

- Issue: `RAY-100`
- Title: 终端激活纳管、联网门槛与本地功能开关
- URL: https://linear.app/ray-app/issue/RAY-100/终端激活纳管联网门槛与本地功能开关
- Linear snapshot: `2026-07-20T09:54:33Z`
- Evidence refreshed: `2026-07-20T10:06:40Z`
- Status at implementation start: `In Progress`
- Milestone: `P5：商业运营`
- Priority: `Urgent`
- Relations: no declared blockers, blocked issues, related issues, duplicates, releases, or customer needs
- Baseline: `c0e4f38113453f2c517158347b499618ce19f6f6`
- RAY-97 server prerequisite: `d8466ead54cc25697185b2811c71937550f1b45b`
- RAY-99 sync prerequisite: `f76d042f598c0459ff57781f3b769fa379c497c2`
- RAY-100 implementation commit: `a4642125c887addf932dbf00acb67839dbc1a5fa`

## Acceptance snapshot and result

- [x] First online activation binds `tenant/site/terminal` and an optional preapproved DO-P4864 device in one reference/production transaction. The activation code is HMAC-indexed, row-locked, single-use, expiry-checked, installation-unique, idempotent for an identical replay, and audited without logging the code.
- [~] The returned short-lived terminal-bound identity supports silent authenticated API use. Real client startup storage/refresh and certificate enrollment are not implemented in this server-owned scope.
- [x] The periodic heartbeat contract is an operational allowlist. Unknown subject/report/raw-data fields are rejected and their values are not echoed.
- [x] Exactly 24 hours since last successful online contact remains allowed; more than 24 hours blocks a new test.
- [x] Exactly 50 pending sessions and exactly 2 GiB pending bytes each independently block a new test.
- [x] A gate never removes existing-report viewing, completed-report download, continued upload, or diagnostics. An in-progress test retains `FINISH_CURRENT_TEST`; `START_NEW_TEST` is withheld.
- [~] Ed25519 License signature, tenant/terminal binding, validity window, status/revocation, canonical feature flags, and cache serialization are automatically verified. Client secure cache/key rotation and a production License issuance backend are not integrated here.
- [x] Explicit clock rollback and invalid credential states require support.
- [~] Re-evaluating the pure policy after a fresh successful online time automatically clears the offline gate. Client network-monitor wiring is not implemented here.
- [~] A temporary authorization outage within the 24-hour window does not block a new test in the policy, and an already-created session can continue uploading after terminal revocation while its short-lived credential remains valid. Real acquisition/process behavior during an outage is not integration-tested.

`[x]` means repeatable automated evidence exists in this repository. `[~]` means the cloud/shared-contract part is complete but client or deployed integration evidence is missing.

## Implementation files and key decisions

- `cloud/device_management/service.py`, `cloud/device_management/__init__.py`
  - HMAC-protect activation-code lookup, consume a code through the repository, issue a short-lived terminal token, and record route-bound heartbeats.
- `cloud/api/app.py`, `cloud/api/errors.py`
  - Add the approved `POST /v1/terminals/enroll` and `POST /v1/terminals/{terminal_id}/heartbeats` surface, safe activation errors, and device-service dependency injection.
- `cloud/api/repository.py`
  - Deterministic reference adapter for one-time enrollment, device binding, terminal status, privacy-safe heartbeats, and idempotent replay.
  - Existing-session lookup permits controlled upload for a non-active terminal; new session creation and heartbeat still require `ACTIVE`.
- `cloud/api/postgres.py`
  - Production activation transaction uses a separate enrollment pool because the tenant is not trusted until the code resolves. It locks/consumes the code, creates terminal/device binding, writes idempotency and safe audit records atomically.
  - Authenticated heartbeat uses the normal tenant-scoped RLS transaction, validates active terminal/device binding, records the heartbeat, updates terminal health, and stores the idempotent response.
- `cloud/migrations/0001_p3_cloud_platform.sql`
  - Allows an enrollment code to prebind one approved tenant device with a composite tenant-aware foreign key.
- `shared/contracts/device_policy.py`, `shared/contracts/__init__.py`
  - Strict cacheable signed License, pinned Ed25519 verifier, feature flags, approved threshold defaults, clock rollback detection, and an explicit allowed-capability decision.
- `cloud/api/README.md`
  - Documents the isolated enrollment-role boundary and production composition.
- `cloud/tests/test_device_management.py`, `test_device_management_api.py`, `test_device_policy.py`, plus focused migration/ingestion regression additions
  - Cover single use, replay, expiry, token tamper/binding, heartbeat privacy, threshold boundaries, License tamper/revocation, safe capabilities, recovery reevaluation, and revoked-terminal upload semantics.

Key decisions:

- Activation codes are never stored or queried as plaintext by the service; a server-only HMAC digest is the lookup key.
- The main tenant API role keeps forced RLS and no `BYPASSRLS`. Pre-authentication code resolution requires a distinct, least-privilege enrollment pool; it must never serve authenticated tenant traffic.
- License signatures cover canonical JSON with normalized, sorted feature flags. A changed feature set invalidates the signature.
- License or connectivity policy can block only starting a new test. It cannot abort an active test or erase/view-block already collected data.
- Revocation blocks new sessions immediately, while an existing session may finish upload using a still-valid short-lived token. Credential expiry/recovery after revocation requires an explicit deployment policy and is not inferred here.

## Verification commands and results

Initial RED evidence:

```text
PYTHONPATH=. /private/tmp/feetforceplate-p3-venv/bin/python -m unittest cloud.tests.test_device_policy cloud.tests.test_device_management -v
ModuleNotFoundError: No module named 'shared.contracts.device_policy'
ImportError: cannot import name 'ActivationCodeInvalid'
Ran 2 tests; FAILED (errors=2)
```

Additional RED evidence was captured before each implementation boundary:

- API tests failed because `ServiceContainer` had no `devices` dependency.
- Migration test failed because `device.enrollment_codes` had no device prebinding field/FK.
- Revocation test failed because the reference repository rejected upload for an already-created session.
- Extreme retry overflow was fixed under RAY-99 and remains in the full regression suite.

Targeted GREEN evidence:

```text
PYTHONPATH=. /private/tmp/feetforceplate-p3-venv/bin/python -m unittest cloud.tests.test_device_policy -v
Ran 8 tests; OK

PYTHONPATH=. /private/tmp/feetforceplate-p3-venv/bin/python -m unittest cloud.tests.test_device_management -v
Ran 5 tests; OK

PYTHONPATH=. /private/tmp/feetforceplate-p3-venv/bin/python -m unittest cloud.tests.test_device_management_api -v
Ran 2 tests; OK

PYTHONPATH=. /private/tmp/feetforceplate-p3-venv/bin/python -m unittest cloud.tests.test_migration_contract -v
Ran 6 tests; OK
```

Full regression evidence:

```text
PYTHONPATH=. /private/tmp/feetforceplate-p3-venv/bin/python -m unittest discover -s cloud/tests -v
Ran 65 tests in 0.140s; OK
```

Compilation and whitespace evidence:

```text
PYTHONPATH=. /private/tmp/feetforceplate-p3-venv/bin/python -m compileall -q cloud shared
exit 0

git diff --check
exit 0
```

## Automatic versus integration/manual verification boundary

Automatically verified here:

- one-time/expired/idempotent activation behavior and terminal/token binding;
- HMAC activation lookup and no raw code in error evidence;
- heartbeat contract privacy allowlist and no rejected value echo;
- token tamper/expiry behavior and active-terminal heartbeats;
- exact 24-hour, 50-session, and 2-GiB boundaries;
- safe-finish/report/upload/diagnostic capabilities under combined gates;
- Ed25519 License tamper, binding, revocation, time-window, feature, and cache round-trip behavior;
- time rollback/support decision and silent policy reevaluation after network recovery;
- new-session denial plus existing-session upload after revocation;
- migration shape, production code compilation, and all prior RAY-97/RAY-99 regressions.

Not verified here:

- live PostgreSQL 15 migration, isolated enrollment-role grants/BYPASSRLS audit, concurrent activation race, or real audit inspection;
- actual client OS secure storage, startup silent login, token/certificate rotation, signed License cache/key rotation, or revocation polling;
- actual client gate wiring at the “start test” command boundary;
- network monitor behavior and automatic unlock in a running process;
- real acquisition/report continuity during an authorization outage;
- pressure-device discovery/binding on hardware, manual operator recovery, or UI wording;
- production License issuance, Feature Flag administration, and upgrade/config rollback, which also depend on RAY-98 operations scope.

These missing client, live-database, hardware, and operational checks prevent `Done`. RAY-100 is eligible only for `In Review` after the implementation/evidence commits.

## 2026-07-31 本机软件合同回读与 Linear 收口

本轮重新对照当前 Linear 的 10 项验收条件，复验云端激活/心跳、共享
License 与门槛策略、客户端 P-05 新检测门控，以及本地 SQLite 待传状态。
当前可由仓库代码和本机自动测试直接证明 6/10：

- [x] 首次在线激活的一次性、过期、幂等和 tenant/site/terminal/device
  绑定软件事务；真实 PostgreSQL 部署与并发审计仍属于部署验收。
- [x] 周期心跳严格使用运营字段白名单，并拒绝且不回显受试者/报告/
  原始数据字段。
- [x] 最近成功联网恰好 24 小时仍允许，超过才限制新测试；该门槛已接入
  客户端 P-05 的 `network_gate`。
- [x] 50 个待传会话或 2 GiB 待传数据各自独立限制新测试，并由本地
  SQLite 快照事务计算。
- [x] 门槛只移除 `START_NEW_TEST`；进行中会话、既有报告、继续上传与
  诊断能力仍保留。
- [x] 时间回拨与无效凭据进入支持状态。

仍保留 4 项：客户端安全凭据存储与启动静默登录；License 安全持久缓存/
密钥轮换/真实吊销轮询；运行中网络恢复后的自动重新校验与 UI 解锁；真实
采集进程在授权服务短暂故障下的连续性。策略纯函数已经覆盖其中部分规则，
但不能替代运行中集成证据。

专项命令通过仓库规定的 `./scripts/local-env.sh` 运行，结果为
`28 passed in 0.99s`；JUnit `pytest-local-closeout-20260731.xml`，SHA-256
`7b7e77deebce40c0ef7d0af3772b069fc0fe6bbdc42b42438fc471f39fc297c3`。
同一代码工作树的全仓新鲜回归为
`622 passed, 3 existing collection warnings, 9 subtests passed in 55.48s`；
JUnit 位于 `../RAY-96/pytest-full-local-closeout-20260731.xml`，SHA-256
`7bae6ba1169045dd767527fce57ab4d4595959f984da6b86209f227d39a94048`。
因此只同步 6 项到 Linear，状态保持 `In Review`，不标记 Done。

## Failures and limitations

## 2026-08-05 实机演示入口与资产编号启动门

本轮将已通过的 DO-P4864 实机基础能力组合为显式的本地演示入口：

- `python main.py --live-demo ...` 仅接受已连接的压力板；它先做空载基线、
  实机采集、硬件质量门和加密本地提交，再由现场看护人员逐段确认四段站立动作。
- 任一段未确认、发生扶持/失衡/提前睁眼，或非交互运行时，程序保留本地采集但
  **不生成报告**。只有四段均由现场人员明确确认且实机质量门已通过时，才生成
  一份匿名、仅含左右相对负重和相对热图的本地基础 PDF；不会上传，也不输出诊断、
  风险评分、COP 或绝对力。
- 当前资产编号会话进入启动门时不再以 `session.hardware_id` 去匹配 USB 元数据。
  已连接的 CH340 板没有 USB serial；资产编号由首次激活/后续 Lease 绑定，启动门
  只验证物理连接和空载状态，避免把端口/USB 元数据误作设备业务身份。

已连接的实际设备 `/dev/cu.usbserial-130` 在 2026-08-05 通过启动门，观察到
`BOOTSTRAPPING → WAITING_FOR_EMPTY → COLLECTING_BASELINE → PASSED`；随后 P-07
实机显示运行 15 秒，读取 305 帧（20.7 Hz）、窗口截图成功保存且读线程正常关闭。
上述运行没有受试者、持久会话、报告或上传，不能替代本轮新增入口所需的受监督
80 秒四段实际采集。

本机回归：

```text
QT_QPA_PLATFORM=offscreen ./scripts/local-env.sh python main.py --live-demo --help
  exit 0

QT_QPA_PLATFORM=offscreen ./scripts/local-env.sh python -m pytest \
  client/tests/test_live_hardware_demo.py \
  client/tests/test_live_hardware_demo_script.py \
  client/tests/test_ray_84_live_display_harness.py \
  client/tests/test_ray_114_packaged_entry.py \
  client/tests/test_seed_hardware_identity.py \
  client/tests/test_seed_access_runtime.py -q
20 passed in 1.87s
```

本次尚未启动四段受监督采集：闭眼和半串联站立具有现场安全风险，必须待现场人员
确认已看护、受试者准备好且可随时中止后运行。此前的 15 秒空载显示证据不能冒充
这一步；RAY-100 继续保持 `In Review`。

## 2026-08-04 资产编号首次激活替换（本机自动化证据）

本次依据实机观察更新绑定口径：已连接的 CH340 DO-P4864 在 macOS 上可用，
但不提供 USB serial number。因此 USB 仅表示“发现一块可用压力板”，不能再
作为 License/设备的身份来源。首次激活的唯一绑定值改为设备标签或二维码的
`FFP-DP4864-000001` 格式资产编号；终端安装 UUID 仍只表示电脑安装实例。

- `POST /v1/access/inventory-activate` 对一个已配对的库存设备/激活码执行单一
  事务：锁定库存、创建租户/账号/硬件/License/安装记录、签发 License，随后
  将设备和 License 库存一并标记为已激活。
- 客户端 P-00 新增 `assetSerialInput`，仅在已检测到一块可用压力板并已扫描/输入
  资产编号和激活码时才可激活；界面不展示 USB 序列号或端口路径。
- `cloud/migrations/0006_inventory_activation_pairing.sql` 新增设备库存到 License
  库存的一对一关联。若 0005 已产生未配对的历史库存，迁移会安全失败，要求按
  实际交付清单导入配对，不能依 UUID 排序猜测绑定关系。

本机验证（仓库规范环境）：

```text
QT_QPA_PLATFORM=offscreen ./scripts/local-env.sh python -m pytest \
  client/tests/test_ray_96_access_diagnostic_events.py \
  cloud/tests/test_access_api.py \
  client/tests/test_seed_hardware_identity.py \
  client/tests/test_seed_access_runtime.py \
  client/tests/test_seed_activation_ui.py \
  client/tests/test_institution_access_ui.py \
  client/tests/test_ray_114_packaged_entry.py -q
35 passed in 1.44s
```

全仓 Python 回归另以临时 JUnit 写入 `/private/tmp`，结果为 `861 passed,
1 skipped, 0 failures, 0 errors`；该报告没有提交，也不包含凭据、原始帧或
客户数据。

这证明的是本机合同、UI 组合和内存参考仓储的行为，不代替真实 PostgreSQL
迁移/角色权限、已有库存配对导入、云端重启或现场操作验收。因此 RAY-100 保持
`In Review`，不能标记 `Done`。

- The production enrollment path deliberately requires a separate pre-authentication database role. Its exact grants and deployment isolation cannot be proven by source tests and must be reviewed in the real environment.
- Current terminal identity is a short-lived server HMAC token. It proves API contract binding, not device-held private-key possession or certificate attestation.
- Controlled upload after revocation lasts only while an already-issued token remains valid; post-expiry recovery must follow an explicit revocation-reason policy.
- No secrets, personal data, activation codes, raw pressure frames, or customer report data are stored in this evidence directory.

## 2026-07-31 Aliyun 网络集成环境

已在 `aliyun-agentic` 的公网 TCP 7443 上部署显式标记为 `integration` 的
HTTPS 环境，并通过真实公网完成 readiness、一次性终端激活和终端心跳。
部署详情、TLS 指纹、源码哈希、权限检查和全仓 `625 passed` 回归见
`aliyun-network-integration-20260731.md`；JUnit 为
`pytest-aliyun-network-deployment-20260731.xml`，SHA-256 为
`673ce7ccba9df26b9263a1167d2fb334fff2c93d2e9fad250af121f5d67804ba`。

该环境仍使用进程内存仓储和对象存储、自签名证书及用户 crontab。它强化已
勾选的激活/心跳证据，但没有新增完成启动静默登录、License 安全缓存与轮换、
网络恢复自动解锁或真实采集连续性，所以 Linear 保持 `6/10`、`In Review`。

## 2026-08-01 account-bound License client refresh

The current client uses provider-provisioned account activation and no customer
tenant-search/create/admin controls. Login on a replacement computer creates a
new client installation while keeping the same account-bound `license/2` and
physical hardware identity. Stable USB serial identity is verified before the
device opens; computer identity does not own the License.

`pytest-seed-client-access.xml` records 248 passing client tests. Deterministic
native Qt captures under `seed-access-ui/` show activation, login, session lock
and suspended-License states. These prove local packaged composition and UI
behavior. Aliyun now proves the synthetic-hardware HTTPS activation, login,
lease, heartbeat and upload-metadata lifecycle. A real physical device run,
customer-domain/public-CA/443 ingress and operator acceptance remain open; the
issue must not be marked Done for hardware-specific criteria yet.
