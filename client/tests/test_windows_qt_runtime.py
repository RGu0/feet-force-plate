from __future__ import annotations

from pathlib import Path

from client.app.packaging.windows_qt_runtime import add_windows_qt_dll_directories


ROOT = Path(__file__).parents[2]


def test_windows_qt_runtime_registers_pyside_and_shiboken_directories(
    monkeypatch, tmp_path: Path
) -> None:
    """Frozen Qt imports need both package directories before QtCore loads."""

    for directory in ("PySide6", "shiboken6"):
        (tmp_path / directory).mkdir()

    registered: list[Path] = []
    monkeypatch.setattr(
        "client.app.packaging.windows_qt_runtime.os.add_dll_directory",
        lambda directory: registered.append(Path(directory)),
    )

    handles = add_windows_qt_dll_directories(tmp_path)

    assert registered == [tmp_path / "PySide6", tmp_path / "shiboken6"]
    assert len(handles) == 2


def test_portable_spec_registers_the_windows_qt_runtime_hook() -> None:
    spec = (ROOT / "client" / "app" / "packaging" / "FeetForcePlate.spec").read_text(
        encoding="utf-8"
    )

    assert "client.app.packaging.windows_qt_runtime" in spec
    assert "windows_qt_runtime_hook.py" in spec
