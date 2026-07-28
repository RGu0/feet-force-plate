from __future__ import annotations

from client.app.app_icon import application_icon
from client.app.qt_shell import ScreeningWindow
from client.app.startup_validation import StartupValidationWindow


def test_scanalytics_application_icon_is_bundled_and_applied_to_windows(qtbot) -> None:
    assert not application_icon().isNull()

    screening = ScreeningWindow()
    startup = StartupValidationWindow()
    qtbot.addWidget(screening)
    qtbot.addWidget(startup)

    assert not screening.windowIcon().isNull()
    assert not startup.windowIcon().isNull()
