# PyInstaller build contract. Run from the repository root after installing locked build dependencies.
import json
import os
import shutil
import sys
from pathlib import Path
import tomllib

from client.cloud.packaged_defaults import (
    CA_BUNDLE_NAME,
    CONFIG_NAME,
    LICENSE_PUBLIC_KEY_NAME,
    load_packaged_cloud_defaults,
    stage_packaged_cloud_defaults,
)
from client.cloud.windows_bundle import materialize_validated_windows_cloud_runtime

project_root = Path(SPECPATH).resolve().parents[2]
entry_point = project_root / "main.py"
assets = project_root / "client" / "app" / "assets"
device_specifications = project_root / "docs" / "hardware" / "device-specifications"
icon = assets / "FeetForcePlate.icns"
device_specification = project_root / "docs" / "hardware" / "device-specifications" / "do-p4864" / "1.0.json"
required_design_font = assets / "fonts" / "NotoSansSC-VF.ttf"
if not device_specification.is_file():
    raise SystemExit(f"Required device specification is missing: {device_specification}")
if not required_design_font.is_file():
    raise SystemExit(f"Required design font is missing: {required_design_font}")
with (project_root / "pyproject.toml").open("rb") as project_file:
    app_version = tomllib.load(project_file)["project"]["version"]

# PySide6's PyInstaller hooks follow the application's explicit Qt imports;
# collecting every PySide6 submodule would also bundle development tools.
hiddenimports = []
datas = [(str(assets), "client/app/assets")]
datas.append(
    (str(device_specification), "docs/hardware/device-specifications/do-p4864")
)
datas.append((str(device_specifications), "docs/hardware/device-specifications"))

# A packaged build may bind to one environment using public-only inputs.  The
# build source path is never embedded; only validated fixed basenames are
# staged into the runtime resources directory.
cloud_default_source = os.environ.get(
    "FEETFORCEPLATE_CLOUD_DEFAULT_DIRECTORY", ""
).strip()
cloud_delivery_source = os.environ.get(
    "FEETFORCEPLATE_WINDOWS_CLOUD_DELIVERY_DIRECTORY", ""
).strip()
if cloud_default_source and cloud_delivery_source:
    raise SystemExit("select either generic defaults or a signed RAY-321 delivery")
if cloud_delivery_source:
    staged_cloud_defaults = Path(workpath) / "r2-cloud-defaults"
    try:
        materialize_validated_windows_cloud_runtime(
            Path(cloud_delivery_source),
            project_root=project_root,
            runtime_directory=staged_cloud_defaults,
        )
    except (FileExistsError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
elif cloud_default_source:
    staged_cloud_defaults = Path(workpath) / "public-cloud-defaults"
    try:
        source_defaults = load_packaged_cloud_defaults(Path(cloud_default_source))
        if source_defaults is not None and source_defaults.integration_mode:
            raise SystemExit("integration packaging requires a signed RAY-321 delivery")
        stage_packaged_cloud_defaults(
            Path(cloud_default_source), staged_cloud_defaults
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
if cloud_delivery_source or cloud_default_source:
    for resource_name in (CONFIG_NAME, CA_BUNDLE_NAME, LICENSE_PUBLIC_KEY_NAME):
        datas.append((str(staged_cloud_defaults / resource_name), "client/app/resources"))

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
