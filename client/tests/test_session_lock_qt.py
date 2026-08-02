from __future__ import annotations

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QLineEdit, QPushButton, QWidget

from client.app.qt_shell import ScreeningWindow
from client.app.session_lock import LockState, LockTimeout, SessionLockController


def test_qt_lock_overlay_masks_content_and_unlocks_with_account_password(qtbot) -> None:
    clock = [1_000.0]
    controller = SessionLockController(
        lambda password: password == "correct-password",
        timeout=LockTimeout.MINUTES_5,
        monotonic=lambda: clock[0],
    )
    window = ScreeningWindow(session_lock_controller=controller)
    qtbot.addWidget(window)
    window.resize(1280, 720)
    window.show()
    clock[0] += 5 * 60

    window.evaluate_session_lock()

    overlay = window.findChild(QWidget, "sessionLockOverlay")
    assert overlay.isVisible()
    assert overlay.geometry() == window.centralWidget().rect()
    assert window.session_locked
    overlay.findChild(QLineEdit, "sessionUnlockPassword").setText("correct-password")
    qtbot.mouseClick(
        overlay.findChild(QPushButton, "UNLOCK_INSTITUTION_SESSION"),
        Qt.MouseButton.LeftButton,
    )
    assert not window.session_locked
    assert controller.state is LockState.UNLOCKED


def test_lock_waits_for_protected_acquisition_then_background_timer_continues(qtbot) -> None:
    clock = [1_000.0]
    protected = [True]
    controller = SessionLockController(
        lambda _password: True,
        timeout=LockTimeout.MINUTES_5,
        monotonic=lambda: clock[0],
    )
    window = ScreeningWindow(
        session_lock_controller=controller,
        protected_operation_active=lambda: protected[0],
    )
    qtbot.addWidget(window)
    window.show()
    ticks = [0]
    background = QTimer(window)
    background.setInterval(10)
    background.timeout.connect(lambda: ticks.__setitem__(0, ticks[0] + 1))
    background.start()
    clock[0] += 5 * 60

    window.evaluate_session_lock()

    assert controller.state is LockState.LOCK_PENDING
    assert not window.session_locked
    protected[0] = False
    window.evaluate_session_lock()
    assert window.session_locked
    qtbot.waitUntil(lambda: ticks[0] >= 2, timeout=500)
    assert background.isActive()
    assert Qt.MouseButton.LeftButton is not None
