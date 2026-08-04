# FeetForcePlate

面向养老机构、体检机构、医疗健康服务和体育/康复辅助分析场景的足底压力健康筛查与云端分析平台。

## 设计文档

- [总体架构设计](docs/架构设计文档.md)
- [产品需求文档（PRD）](docs/产品需求文档_PRD.md)
- [通信接口设计文档](docs/通信接口设计文档.md)
- [数据库设计文档](docs/数据库设计文档.md)
- [模块设计索引](docs/modules/README.md)
- [已批准设计规范](docs/superpowers/specs/2026-07-20-institution-screening-platform-design.md)
- [通信与数据库批准规范](docs/superpowers/specs/2026-07-20-communication-and-database-design.md)

当前仓库处于设计与硬件基线验证阶段；构建、测试通过不代表真机、标定或专业指标已经完成验证。

面向机构的首个 Windows 交付格式为受控的签名便携 ZIP。发布负责人必须完成[便携版发布放行清单](docs/release/windows-portable-release-gate.md)，操作员按[便携版使用说明](docs/release/windows-portable-user-guide.md)安装和启动。未签名开发包、未完成 License/云端配置或未完成真机验收的包不得交付。

## 本机开发环境

不要在 OneDrive 中共享或复用 `.venv`。虚拟环境包含创建它的电脑的绝对解释器路径，跨用户目录、操作系统或 CPU 架构都会失效；应同步 `pyproject.toml`、`uv.lock` 和 `.python-version`，在每台电脑本机重建环境。

每台电脑安装一次 [uv](https://docs.astral.sh/uv/)，然后通过对应平台的包装脚本使用。不要直接运行未设置 `UV_PROJECT_ENVIRONMENT` 的 `uv sync` 或 `uv run`，否则 uv 默认仍会在项目目录创建 `.venv`。

macOS / Linux：

```bash
./scripts/local-env.sh
```

Windows PowerShell：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\local-env.ps1
```

包装脚本会根据锁文件创建或更新当前用户的私有环境：

```text
macOS/Linux: $HOME/.cache/feetforceplate/venv
Windows:     %LOCALAPPDATA%\FeetForcePlate\venv
```

这些环境不位于 OneDrive，不会被其他电脑同步覆盖。常用命令：

```bash
QT_QPA_PLATFORM=offscreen ./scripts/local-env.sh python -m pytest
./scripts/local-env.sh python main.py
```

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
powershell -ExecutionPolicy Bypass -File .\scripts\local-env.ps1 python -m pytest
powershell -ExecutionPolicy Bypass -File .\scripts\local-env.ps1 python main.py
```

## 正式入口与机构访问

正式入口先显示 P-00 机构登录页，并可进入 P-00b License 注册页：

```bash
./scripts/local-env.sh python main.py
```

当前页面已具备账号、密码、License、机构信息及密码确认的交互校验，但真实 License 验证、机构账户创建和登录服务尚未接入。除下述精确匹配的本机 UI 测试码外，授权码只会显示“待联网校验”，不得视为已激活；输入有效账号也不会进入设备检测。

### 本机 UI 测试 License

用于 P-00b 注册页的公开本机测试码：`FFP-2026-TEST-0001`。

操作：在 P-00 点击“使用 License 注册”，填入该值并填写机构名称、账号和两次密码，然后点击“激活并创建账户”。预期会返回登录页并预填机构账号；输入刚设置的密码即可完成本机登录验证。

此测试账户只保存在当前应用进程的内存中，关闭应用即失效；它不连接网络、不创建正式机构账户、不授予设备检测或其他正式权限，也不得用于生产部署或客户交付。

## 本地 V1 回放演示

本地回放是独立、可持久化的调试闭环，不会访问网络、上传数据或尝试连接串口：

```bash
./scripts/local-env.sh python main.py --replay
```

按界面顺序录入受试者、确认必要授权，并开始四段引导。程序以 1× 速度回放仓库内固定的脱敏真机 fixture：并足睁眼、并足闭眼、左脚在前半串联、右脚在前半串联，各 20 秒；第四段完成后才运行本地 V1 调试分析并生成可预览、导出和在历史记录重新打开的 PDF。

开发时可用更高速度缩短等待时间（例如 `--replay --replay-speed 20`）；该参数不应在演示中替代默认的 1× 体验。旧的静态设计演示须显式指定 `--demo`：

```bash
./scripts/local-env.sh python main.py --replay --replay-speed 20
./scripts/local-env.sh python main.py --demo
```

### 本机离线 MVP 验证

以下命令从已验证的四阶段 fixture（1,658 帧）开始，模拟解码后的硬件帧；不会打开 HTTP 客户端、不会上传数据、不会连接真实设备。它会自动完成建档、必要授权、预检、四个站位阶段、本地 V1 调试分析、PDF 导出和本地历史记录重开：

```bash
QT_QPA_PLATFORM=offscreen ./scripts/local-env.sh python main.py \
  --replay --verify --replay-speed 500 \
  --output-dir /absolute/path/to/local-mvp-validation
```

`--verify` 必须与 `--replay` 和一个空的 `--output-dir` 一起使用。成功时输出目录包含六张 UI PNG（预检、四个阶段和报告预览）、`report.pdf` 与 `summary.json`；摘要只记录 fixture SHA-256、阶段帧数、算法状态和报告标识，不复制原始矩阵、身份信息或凭据。所有输出均标注为“回放调试数据”，并非真实测量，不能用于诊断、风险判断、临床结论或客户交付。

所有工作台页面、结果和 PDF 都是“回放调试数据”，不代表本次受试者真实测量，不用于诊断或风险判断。真实 DO-P4864、License 联网验证、服务端密钥集下发和云端算法/数据管理尚未接入这个入口。

回放不是原始帧直通 UI：每帧均先经过 DO-P4864 的版本化标准化路径（显式基线、坏点处理、零点校正与设备适配器）。本 fixture 已知的连续坏区只在派生帧中排除；原始 fixture 和原始审计输入不被改写。实时设备显示也必须提供已批准的“基线＋已知坏区掩码”处理配置，运行时不再允许无标准化直通。

可通过 `FEETFORCEPLATE_VENV` 为当前机器指定另一个私有环境目录；`UV_BIN` 可指定本机 uv 的位置。修改依赖后可以直接运行 `uv lock` 更新跨平台锁文件，再通过包装脚本同步本机环境。
