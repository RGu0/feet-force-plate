# PyInstaller build contract. Run from the repository root after installing locked build dependencies.
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

hiddenimports = collect_submodules("PySide6")
datas = collect_data_files("PySide6")
datas += Tree("client/app/assets", prefix="client/app/assets")

analysis = Analysis(
    ["client/app/packaged_entry.py"],
    pathex=["."],
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
    analysis.binaries,
    analysis.datas,
    [],
    name="FeetForcePlate",
    console=False,
    disable_windowed_traceback=True,
)
