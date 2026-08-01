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
