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

可通过 `FEETFORCEPLATE_VENV` 为当前机器指定另一个私有环境目录；`UV_BIN` 可指定本机 uv 的位置。修改依赖后可以直接运行 `uv lock` 更新跨平台锁文件，再通过包装脚本同步本机环境。
