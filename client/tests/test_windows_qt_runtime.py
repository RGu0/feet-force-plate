from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).parents[2]


def test_frozen_windows_hook_registers_dll_directories_before_importing_client(
    monkeypatch, tmp_path: Path
) -> None:
    """Frozen Qt imports need both package directories before QtCore loads."""

    for directory in ("PySide6", "shiboken6"):
        (tmp_path / directory).mkdir()

    registered: list[Path] = []
    monkeypatch.setattr(
        os,
        "add_dll_directory",
        lambda directory: registered.append(Path(directory)),
        raising=False,
    )
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.delitem(sys.modules, "client.app", raising=False)

    hook = ROOT / "client" / "app" / "packaging" / "windows_qt_runtime_hook.py"
    namespace = runpy.run_path(str(hook))

    assert "client.app" not in sys.modules
    assert registered == [
        tmp_path,
        tmp_path / "PySide6",
        tmp_path / "shiboken6",
    ]
    assert len(namespace["_WINDOWS_QT_DLL_DIRECTORIES"]) == 3

def test_frozen_windows_hook_rejects_a_package_without_qt_directories(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(os, "add_dll_directory", lambda _directory: object(), raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

    hook = ROOT / "client" / "app" / "packaging" / "windows_qt_runtime_hook.py"

    try:
        runpy.run_path(str(hook))
    except RuntimeError as error:
        assert "PySide6" in str(error)
        assert "shiboken6" in str(error)
    else:
        raise AssertionError("missing frozen Qt directories must fail before app import")


def test_portable_spec_registers_the_standalone_windows_qt_runtime_hook(
    monkeypatch, tmp_path: Path
) -> None:
    captured: dict[str, object] = {}

    class _Analysis:
        def __init__(self, *_args, **kwargs) -> None:
            captured.update(kwargs)
            self.pure = []
            self.scripts = []
            self.binaries = [
                ("icuuc.dll", "C:/external-runtime/icuuc.dll", "BINARY"),
                ("icudt78.dll", "C:/external-runtime/icudt78.dll", "BINARY"),
                ("PySide6/Qt6Core.dll", "C:/PySide6/Qt6Core.dll", "BINARY"),
            ]
            self.datas = []

    analysis: _Analysis | None = None

    def create_analysis(*args, **kwargs) -> _Analysis:
        nonlocal analysis
        analysis = _Analysis(*args, **kwargs)
        return analysis

    monkeypatch.delenv("FEETFORCEPLATE_CLOUD_DEFAULT_DIRECTORY", raising=False)
    monkeypatch.delenv("FEETFORCEPLATE_WINDOWS_CLOUD_DELIVERY_DIRECTORY", raising=False)
    monkeypatch.delenv("FEETFORCEPLATE_SUPPORT_RECIPIENT_FILE", raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    spec = ROOT / "client" / "app" / "packaging" / "FeetForcePlate.spec"
    runpy.run_path(
        str(spec),
        init_globals={
            "SPECPATH": str(spec.parent),
            "workpath": str(tmp_path),
            "Analysis": create_analysis,
            "PYZ": lambda *_args: object(),
            "EXE": lambda *_args, **_kwargs: object(),
            "COLLECT": lambda *_args, **_kwargs: object(),
        },
    )

    assert captured["hiddenimports"] == []
    assert captured["runtime_hooks"] == [
        str(ROOT / "client" / "app" / "packaging" / "windows_qt_runtime_hook.py")
    ]
    assert analysis is not None
    assert analysis.binaries == [
        ("PySide6/Qt6Core.dll", "C:/PySide6/Qt6Core.dll", "BINARY")
    ]
