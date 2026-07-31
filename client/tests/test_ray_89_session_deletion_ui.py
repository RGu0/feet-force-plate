from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QDialog, QLabel, QLineEdit, QPushButton

from client.app.pages import PageId
from client.app.qt_shell import ScreeningWindow
from client.app.session_deletion import SessionDeletionConfirmationRequired


class _DeletionService:
    def __init__(self) -> None:
        self.session_ids = ["session-verified-1"]
        self.deleted: list[str] = []

    def candidates(self) -> tuple[str, ...]:
        return tuple(self.session_ids)

    def delete(self, *, session_id: str, confirmation: str) -> None:
        if confirmation != f"删除 {session_id}":
            raise SessionDeletionConfirmationRequired()
        self.session_ids.remove(session_id)
        self.deleted.append(session_id)


def test_session_deletion_requires_exact_single_session_confirmation(qtbot) -> None:
    window = ScreeningWindow()
    qtbot.addWidget(window)
    window.show()
    service = _DeletionService()

    window.set_session_deletion_available(True)
    entry = window.page_widget(PageId.SUPPORT).findChild(
        QPushButton, "OPEN_SESSION_DELETION"
    )
    assert entry.isHidden() is False
    window.show_session_deletion(service)  # type: ignore[arg-type]
    dialog = window.findChild(QDialog, "sessionDeletionDialog")
    selector = dialog.findChild(QComboBox, "sessionDeletionSelector")
    confirmation = dialog.findChild(QLineEdit, "sessionDeletionConfirmation")
    button = dialog.findChild(QPushButton, "CONFIRM_SESSION_DELETION")
    status = dialog.findChild(QLabel, "sessionDeletionStatus")

    assert selector.currentData() == "session-verified-1"
    button.click()
    assert service.deleted == []
    assert "未删除" in status.text()

    confirmation.setText("删除 session-verified-1")
    button.click()
    assert service.deleted == ["session-verified-1"]
    assert "未影响其他会话" in status.text()
    assert button.isEnabled() is False
