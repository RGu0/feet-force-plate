# RAY-96 Evidence

- Issue：`RAY-96` 机构采集端打包、安装与受控升级
- URL：https://linear.app/ray-app/issue/RAY-96/机构采集端打包安装与受控升级
- 首次抓取时间：2026-07-20T08:54:41Z
- 开始时间：2026-07-20T10:37:09Z
- 开始时状态：Backlog；实现中状态：In Progress；当前状态：In Review
- 状态回读确认：2026-07-20T10:48:47.938Z
- 里程碑：P2：一键筛查
- 优先级：Medium
- 关系：无显式阻塞、依赖或重复关系

## 验收条目快照与当前结论

- [ ] Windows 安装器与 CH340 驱动检查：已实现 PyInstaller Windows 目标合同、驱动探测端口和进入设备前门控；尚未在 Windows 生成/签名安装器或验证 CH340 安装。
- [x] macOS 开发/试点包及签名流程：已生成并启动验证 arm64 onedir 开发 `.app`，严格深层 ad-hoc 签名校验通过；Developer ID、hardened runtime、公证、Gatekeeper 与 universal2 仍是外部试点边界。
- [ ] 首次联网激活及机构/站点/终端绑定：客户端只有可注入 `ActivationPort` 的门控；真实 License 后台激活与绑定尚未联调。
- [x] 用户数据、加密分段和日志目录规范：安装目录与数据库、加密分段、日志、配置缓存分离，并声明卸载保留集合。
- [x] 升级前兼容、数据库迁移、失败回滚：覆盖签名、摘要、最低版本、数据模式、空闲状态、数据库快照、迁移和应用/数据库联合回滚。
- [x] 受控升级与最低支持版本：升级策略拒绝未签名、摘要不符、版本过低、采集中或模式不兼容的候选包。
- [ ] 双平台安装/升级/卸载/数据保留冒烟测试：数据保留合同和回滚自动测试通过；缺 Windows/macOS 目标机真实冒烟。
- [x] 构建记录软件、协议和数据模式版本：确定性 manifest 包含应用、协议、报告模式、数据模式、最低版本、commit 与目标平台。
- [ ] 安装后非技术操作员可直接进入工作台：激活门控自动测试通过；打包入口目前仅为启动烟测壳层，缺真实适配器组合及操作员人工验收。

## 实现文件与关键决策

- `client/app/deployment.py`：运行目录、构建 manifest、激活/绑定门控、CH340 探测、受控升级策略与联合回滚。
- `client/app/packaged_entry.py`：PySide 打包启动烟测入口。
- `client/app/packaging/FeetForcePlate.spec`、`build-config.json`、`README.md`：PyInstaller 双平台合同、签名/驱动/持久数据策略与真实构建边界。
- `client/reporting/pdf.py`：A4 本地基础报告 PDF，包含 report ID/version、脱敏受试者、协议、白名单指标、相对热力图、筛查非诊断声明和来源页脚。
- `client/reporting/delivery.py`：`.partial` 原子导出、安全临时打印文件、打印确认信息与可注入打印端口。
- `client/tests/test_ray_96_deployment.py`：目录、manifest、激活、驱动、升级拒绝和失败回滚测试。
- `client/tests/test_ray_96_pdf_delivery.py`：PDF 可读性、原子导出、安全打印文件名及确认信息测试。

关键决策：客户端只依赖激活、驱动、升级、打印抽象端口，不实现 License 后台、不直接访问串口/数据库私表/HTTP；签名材料只能来自受保护 CI；升级仅在空闲时执行并将应用与数据库视为同一回滚单元；打印/导出只处理已门控的本地基础报告。

## 证据文件

- [构建 manifest（合同 dry run）](dry-run-build-manifest.json)
- [合成基础报告 PDF](sample-basic-report.pdf)
- [合成报告第一页预览](sample-basic-report-page1.png)
- [pytest JUnit 结果](pytest-results.xml)

示例全部使用合成、非客户数据。PDF 预览已人工目视检查页面为白色 A4、正文可读、无明显截断，包含版本、时间、筛查非诊断说明和相对热力图；这不等同于实体打印机验收。

## 验证命令与结果

```bash
QT_QPA_PLATFORM=offscreen /private/tmp/feetforceplate-subtask-b-venv/bin/python -m pytest client/tests -q --junitxml=docs/evidence/linear/RAY-96/pytest-results.xml
/private/tmp/feetforceplate-subtask-b-venv/bin/python -m compileall -q client/app client/workflow client/local_analysis client/reporting client/tests
rg -n "^(import|from) (serial|sqlite3|requests|httpx|urllib|aiohttp)" client/app client/workflow client/local_analysis client/reporting
git diff --check
```

- pytest：`89 passed in 0.54s`，JUnit 已保存。
- compileall：通过。
- 禁止直接依赖扫描：0 命中。
- `git diff --check`：通过。

## 自动测试、真机与人工边界

自动测试验证了领域合同、拒绝路径、回滚顺序、PDF 结构、原子文件语义和安全展示信息。以下事项没有在本地自动测试中完成，因此 issue 只能进入 In Review：

- Windows 安装器生成、代码签名、CH340 实装、升级/卸载及数据保留。
- macOS app 签名、公证、Gatekeeper、升级/卸载及数据保留。
- 真实联网激活与机构/站点/终端绑定后台联调。
- 从已安装应用进入真实工作台、设备采集和升级中断恢复。
- 实体打印机版式、分页、字体、缩放和操作员确认流程。
- 打包环境的 CJK 字体回退/随包分发验证。

此外，当前环境仍未持有 Windows 构建工具、Developer ID 分发签名/Apple 公证凭据、真实打印机或 Windows CH340 目标机；正式默认包仍没有真实 License 后台或最终生产工作台组合根。

## 2026-07-31 本机 macOS 开发包与软件合同收口

本轮先用真实 PyInstaller 6.21.0 构建发现并修复了三个会直接阻断发布的缺陷：spec 相对路径解析到了错误目录；直接冻结 `client/app/packaged_entry.py` 导致包内相对导入失败；收集整个 PySide6 工具链把 `Assistant.app` 等开发工具带入 bundle，导致深层签名失败并把包体放大到 796 MB。随后把正式入口改为仓库 `main.py`、路径绑定到 `SPECPATH` 推导的仓库根目录、切换为标准 onedir bundle，并只依赖 PyInstaller 的 import-driven Qt hooks。

最终本机产物：

- 环境：macOS 26.5.2 arm64；Python 3.11.15；PyInstaller 6.21.0。
- 产物：`FeetForcePlate.app`，arm64 Mach-O，592 个文件，195 MB；临时构建位于 `/private/tmp`，未提交到仓库。
- Bundle ID：`com.steadyhealth.feetforceplate`；`CFBundleShortVersionString=0.1.0`，从 `pyproject.toml` 读取。
- 主可执行 SHA-256：`9dfb640bc748bbf82c952006742d79ba3bde51437b2993e51c2cd291288f64b9`。
- Info.plist SHA-256：`e5ca50eab606d296f7e1cd92dea55f72a639f4278441a60a95786272f843898c`。
- `codesign --verify --deep --strict`：通过；当前是 ad-hoc signature，无 TeamIdentifier。
- `QT_QPA_PLATFORM=offscreen` 启动 5 秒保持运行，无导入或启动异常；验证后以信号安全终止。
- `spctl --assess`：未通过（Code Signing subsystem internal error），因此该包不是可对外分发的已公证试点包。

专项自动测试：`20 passed in 1.56s`；JUnit `pytest-local-closeout-20260731.xml`，SHA-256 `9724e74490e8d9398eb80af1c30b9d8f82c3613a78205c3eabf06b2ad2b634db`。同一工作树全仓新鲜验证：`622 passed, 3 existing collection warnings, 9 subtests passed in 55.48s`；JUnit `pytest-full-local-closeout-20260731.xml`，SHA-256 `7bae6ba1169045dd767527fce57ab4d4595959f984da6b86209f227d39a94048`。

据此可在 Linear 勾选 macOS **开发包**、持久目录规范、升级兼容/迁移/回滚、最低支持版本策略和构建版本记录，共 5/9。仍不勾选 Windows 安装器/CH340、真实联网激活绑定、双平台真实安装升级卸载保留冒烟、安装后非技术操作员直达工作台。RAY-96 保持 `In Review`。

## 提交

- 实现 commit：`c04430984cbd460e0aa8f30f6e2c0e9ef8604235`
- evidence SHA 回填 commit：`7bd7ebeb4cfea80909e6fb34e80c9da2df1056c2`

## 2026-08-02 诊断隐私软件证据（RAY-96 单项）

本节是指定 RAY-96 工作树上的软件级自动化证据；它不是安装、真机、运维或临床验证。本次修复后重新执行前 HEAD 为 `fbb8ee71e1f90956a84c7fba42d0da77cca85e2f`，分支为 `codex/ray-96-diagnostic-privacy`，工作树无未提交实现改动。执行仅覆盖本节所列两份 JUnit 输出、本 README 和 JSON 摘要；未修改实现、计划或其他证据。

### 已运行的命令和精确结果

```bash
./scripts/local-env.sh python -m pytest -q client/tests/test_ray_96_diagnostic_privacy.py client/tests/test_ray_96_access_diagnostic_events.py client/tests/test_ray_96_deployment.py client/tests/test_ray_96_packaged_diagnostics.py client/tests/test_ray_114_packaged_entry.py client/tests/test_ray_115_packaged_telemetry.py --junitxml=docs/evidence/linear/RAY-96/pytest-diagnostic-privacy-closeout-20260802.xml
./scripts/local-env.sh python -m pytest -q --junitxml=docs/evidence/linear/RAY-96/pytest-full-diagnostic-privacy-closeout-20260802.xml
./scripts/local-env.sh python -m ruff check client
./scripts/local-env.sh python -m mypy
./scripts/local-env.sh python -m compileall -q client cloud shared tests
git diff --check
```

- 聚焦矩阵：`60 passed in 1.28s`；JUnit `tests=60, failures=0, errors=0, skipped=0`，SHA-256 `3e99de0a35053ddcf1a40df69df37e333851e7ef9d4f69e0a5d8bb84e2a3ae03`。
- 全量 pytest：`828 passed, 1 skipped, 3 warnings, 21 subtests passed in 118.44s`。JUnit 根汇总为 `tests=850, failures=0, errors=0, skipped=1`（其中 829 个 testcase 元素与 21 个 subtest 相加）。跳过原因：未配置三个 PostgreSQL role DSN。3 条既有警告均为 `TestProtocol` 因自定义构造函数不能被 pytest 收集的 `PytestCollectionWarning`。JUnit SHA-256 `14f7327007d97c71e45219a2fcce852a35bbb62540d96bad90ee0efc7ad17624`。
- Ruff：`All checks passed!`；Mypy：`Success: no issues found in 13 source files`；compileall：通过；`git diff --check`：通过。

JUnit 在 pytest 生成后以确定性 XML 解析/写回步骤脱敏：所有 `hostname` 属性固定为 `local-test-host`，当前工作树根目录前缀从属性与文本中移除，因而跳过信息中的测试位置为仓库相对路径。写回后重新解析两份 XML，确认 tests、testcase、推导 subtests、failures、errors 和 skipped 均未改变；四份本轮 Task 5 证据均已扫描，不含用户路径、Windows 用户路径、用户名、机器主机名、canary 值、私钥块或 bearer 凭据。

### 聚焦矩阵实际证明的范围

- 严格事件合同拒绝任意自由文本及凭据/身份字段；针对密码、一次性激活码、刷新令牌、访问令牌、License 签名材料、私钥材料、患者标识、病历号与联系人等**标签**执行了缺失检查，本文及 JSON 不存储其测试值。
- 私有 JSONL 事件存储以 `0600` 权限写入并校验哈希链；保留三代轮换；只恢复末尾不完整行，拒绝内部损坏；存储失败返回失败而不写回退文件。
- 解密后的固定归档仅有 `manifest.json`、`safe-events.jsonl`、`integrity.json`；归档条目及最终加密诊断文件均断言为 `0600`，归档内容和加密载荷均断言不含上述敏感标签的测试值。
- 资源不合法、记录多字段、哈希链损坏、目标目录无效、原子替换中断和最终替换失败均在测试中失败关闭并清理临时产物；替换失败时已存在目标的字节和权限保持不变。
- P-11 打包工作台只接入诊断导出动作；只读公开收件人资源受到形状/权限检查，缺失或无效资源仅禁用导出且不产生归档；入口组合复用运行时安装标识并记录受限生命周期事件。

实现提交链（最早到当前）为：`f942ff40c019b678c30fecd1ef7ac4ff6cc8d170`、`419d489a240147890d1f8543240ead36ac9b9a0d`、`8e16051ec42059a113d7da9c42a58b6c915b0143`、`71b011570ea21332b2268e47d3ca011a4f2c093c`、`659209bb805c296b128a6dfe2abded4be9853036`、`8093448ea22fe71d1cd280f0a7e686d3eb8d5b75`、`4464d2cb8031fb40a847372d2f115a2beeef2683`、`326108d188f0c75384f2b7a537d08ddea0e7d20b`、修复提交 `f45f546`、回归加固提交 `fbb8ee7`。

### 明确不作的声明

本节先前由 `991b0c0` 记录的运行因启动恢复焦点测试失败而受阻；该结果没有被表述为通过，现由上述修复后新鲜聚焦与全量结果取代。此次证据不证明 Windows 安装器或 CH340 实装/驱动检查，不包含实际安装器或升级日志；不证明已部署支持方密钥的托管、轮换或访问控制；不证明真实硬件、非技术操作员流程、生产环境或网络服务；也不构成临床有效性、安全性、诊断或个体风险结论。
