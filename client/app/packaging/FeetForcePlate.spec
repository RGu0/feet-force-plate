# PyInstaller build contract. Run from the repository root after installing locked build dependencies.
import json
import os
import shutil
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

# This optional build input is a public X25519 recipient resource.  Its source
# path stays in the build process; only its fixed packaged basename is copied.
support_recipient_source = os.environ.get(
    "FEETFORCEPLATE_SUPPORT_RECIPIENT_FILE", ""
).strip()
if support_recipient_source:
    support_recipient_file = Path(support_recipient_source)
    try:
        support_recipient_mode = support_recipient_file.stat().st_mode
    except OSError as exc:
        raise SystemExit("support recipient resource must be a regular file") from exc
    if not support_recipient_file.is_file() or support_recipient_mode & 0o022:
        raise SystemExit("support recipient resource must not be group/world writable")
    try:
        support_recipient_payload = json.loads(
            support_recipient_file.read_text(encoding="utf-8")
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit("support recipient resource must be valid JSON") from exc
    if set(support_recipient_payload) != {"schema_version", "key_id", "public_key"}:
        raise SystemExit("support recipient resource has an invalid schema")
    if support_recipient_payload["schema_version"] != "feetforceplate-support-recipient/1":
        raise SystemExit("support recipient resource has an invalid schema")
    staged_recipient = (
        Path(workpath) / "public-support-recipient" / "support-recipient.json"
    )
    staged_recipient.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(support_recipient_file, staged_recipient)
    os.chmod(staged_recipient, 0o644)
    datas.append((str(staged_recipient), "client/app/resources"))

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
