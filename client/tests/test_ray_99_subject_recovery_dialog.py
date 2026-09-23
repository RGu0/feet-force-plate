from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from PySide6.QtWidgets import QCheckBox, QComboBox, QLabel, QPushButton, QWidget

from client.app.subject_recovery_dialog import SubjectRecoveryDialog
from client.sync.persistent_upload import UploadBlocked
from client.sync.subject_recovery import RecoveryCandidate, RecoveryPreview


class _Service:
    def __init__(self):
        self.sessions = (uuid4(), uuid4())

    def candidates(self):
        return tuple(
            RecoveryCandidate(session_id=session, local_identifier_masked="***0731",
                              started_at=datetime(2026, 9, 23, tzinfo=UTC))
            for session in self.sessions
        )

    def prepare(self, session_id):
        return RecoveryPreview(
            session_id=session_id,
            local_subject_uuid=uuid4(), cloud_subject_uuid=uuid4(),
            local_identifier_masked="***0731", cloud_identifier_masked="***0731",
            research_available=False,
        )


def test_switching_candidate_revokes_previous_operator_confirmation(qtbot):
    parent = QWidget()
    qtbot.addWidget(parent)
    dialog = SubjectRecoveryDialog(_Service(), parent)
    qtbot.addWidget(dialog)
    session_picker = dialog.findChild(QComboBox)
    dialog._prepare()
    boxes = dialog.findChildren(QCheckBox)
    boxes[0].setChecked(True)
    boxes[1].setChecked(True)
    confirm = next(
        button for button in dialog.findChildren(QPushButton)
        if button.text().startswith("确认核对")
    )
    assert confirm.isEnabled()
    assert not boxes[2].isEnabled()

    session_picker.setCurrentIndex(1)
    assert not confirm.isEnabled()
    assert not boxes[0].isChecked()
    assert not boxes[1].isChecked()


def test_integration_lookup_failure_shows_only_safe_diagnostic(qtbot, monkeypatch):
    monkeypatch.setenv("FEETFORCEPLATE_INTEGRATION_MODE", "1")

    class FailingService(_Service):
        def prepare(self, session_id):
            raise UploadBlocked("private server detail", error_code="E-AUT-403")

    parent = QWidget()
    qtbot.addWidget(parent)
    dialog = SubjectRecoveryDialog(FailingService(), parent)
    qtbot.addWidget(dialog)
    dialog._prepare()

    text = " ".join(label.text() for label in dialog.findChildren(QLabel))
    assert "UploadBlocked / E-AUT-403" in text
    assert "private server detail" not in text
    assert all(not box.isEnabled() for box in dialog.findChildren(QCheckBox))
