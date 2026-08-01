# PyInstaller build contract. Run from the repository root after installing locked build dependencies.
import sys
from pathlib import Path
import tomllib

project_root = Path(SPECPATH).resolve().parents[2]
entry_point = project_root / "main.py"
assets = project_root / "client" / "app" / "assets"
icon = assets / "FeetForcePlate.icns"
with (project_root / "pyproject.toml").open("rb") as project_file:
    app_version = tomllib.load(project_file)["project"]["version"]

# PySide6's PyInstaller hooks follow the application's explicit Qt imports;
# collecting every PySide6 submodule would also bundle development tools.
hiddenimports = []
datas = [(str(assets), "client/app/assets")]

analysis = Analysis(
    [str(entry_point)],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz,
    analysis.scripts,
    [],
    name="FeetForcePlate",
    icon=str(icon),
    console=False,
    disable_windowed_traceback=True,
    exclude_binaries=True,
)
bundle_contents = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    name="FeetForcePlate",
)

if sys.platform == "darwin":
    app = BUNDLE(
        bundle_contents,
        name="FeetForcePlate.app",
        icon=str(icon),
        bundle_identifier="com.steadyhealth.feetforceplate",
        version=app_version,
        info_plist={"NSHighResolutionCapable": True},
    )
