from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from PySide6.QtWidgets import QCheckBox, QComboBox, QLabel

from client.app.subject_recovery_dialog import SubjectRecoveryDialog
from client.sync.persistent_upload import UploadBlocked
from client.sync.subject_recovery import RecoveryCandidate, RecoveryPreview


class _Service:
    def __init__(self):
        self.sessions = (uuid4(), uuid4())
        self.status = "PENDING"
        self.clock = datetime.now(UTC)
        self.calls = []

    def now(self):
        return self.clock

    def candidates(self):
        return tuple(
            RecoveryCandidate(session_id=session, local_identifier_masked="***0731",
                              started_at=self.clock)
            for session in self.sessions
        )

    def prepare(self, session_id):
        matched = self.status == "MATCHED"
        return RecoveryPreview(
            session_id=session_id,
            local_subject_uuid=uuid4(), cloud_subject_uuid=uuid4(),
            local_identifier_masked="***0731", cloud_identifier_masked="***0731",
            research_available=True, case_id=uuid4(), status=self.status,
            receipt_id=uuid4() if matched else None,
            receipt_expires_at=self.clock + timedelta(minutes=5) if matched else None,
            original_envelope_sha256="a" * 64,
            platform_ticket_sha256="b" * 64 if matched else None,
        )

    def authorize(self, preview, **kwargs):
        self.calls.append((preview, kwargs))


def _dialog(qtbot, service):
    dialog = SubjectRecoveryDialog(service, None)
    qtbot.addWidget(dialog)
    return dialog


def _refresh(qtbot, dialog):
    dialog._prepare()
    qtbot.waitUntil(lambda: not dialog._lookup_running)


def test_pending_and_expired_cases_cannot_authorize(qtbot):
    service = _Service()
    dialog = _dialog(qtbot, service)
    _refresh(qtbot, dialog)
    assert "待平台核对" in dialog._comparison.text()
    assert not dialog._necessary.isEnabled()
    assert not dialog._confirm.isEnabled()
    service.status = "EXPIRED"
    _refresh(qtbot, dialog)
    assert "回执已过期" in dialog._comparison.text()
    assert not dialog._confirm.isEnabled()
    assert not service.calls


def test_matched_case_requires_fresh_consent_actor_and_session_binding(qtbot, monkeypatch):
    service = _Service()
    dialog = _dialog(qtbot, service)
    service.status = "MATCHED"
    _refresh(qtbot, dialog)
    assert dialog._necessary.isEnabled()
    assert not dialog._research.isChecked()
    assert not dialog._confirm.isEnabled()
    dialog._necessary.setChecked(True)
    assert not dialog._confirm.isEnabled()
    dialog._actor.setCurrentIndex(1)
    assert dialog._confirm.isEnabled()

    session_picker = dialog.findChild(QComboBox, "recovery_sessions")
    session_picker.setCurrentIndex(1)
    assert not dialog._confirm.isEnabled()
    assert not dialog._necessary.isChecked()
    assert dialog._actor.currentIndex() == 0
    _refresh(qtbot, dialog)
    dialog._actor.setCurrentIndex(2)
    dialog._necessary.setChecked(True)
    monkeypatch.setattr("client.app.subject_recovery_dialog.QMessageBox.information", lambda *_: None)
    dialog._authorize()
    qtbot.waitUntil(lambda: not dialog._authorization_running)
    assert service.calls[0][0].session_id == service.sessions[1]
    assert service.calls[0][1]["evidence_type"] == "REPRESENTATIVE_CONFIRMED"
    assert service.calls[0][1]["research_accepted"] is False


def test_receipt_expiry_disables_authorization_at_click(qtbot):
    service = _Service()
    dialog = _dialog(qtbot, service)
    service.status = "MATCHED"
    _refresh(qtbot, dialog)
    dialog._actor.setCurrentIndex(1)
    dialog._necessary.setChecked(True)
    service.clock += timedelta(minutes=16)
    dialog._authorize()
    assert not service.calls
    assert not dialog._confirm.isEnabled()


def test_integration_lookup_failure_shows_only_safe_diagnostic(qtbot, monkeypatch):
    monkeypatch.setenv("FEETFORCEPLATE_INTEGRATION_MODE", "1")

    class FailingService(_Service):
        def prepare(self, session_id):
            raise UploadBlocked("private server detail", error_code="E-AUT-403")

    dialog = _dialog(qtbot, FailingService())
    _refresh(qtbot, dialog)
    text = " ".join(label.text() for label in dialog.findChildren(QLabel))
    assert "UploadBlocked / E-AUT-403" in text
    assert "test_ray_99_subject_recovery_dialog.py:" in text
    assert "private server detail" not in text
    assert all(not box.isEnabled() for box in dialog.findChildren(QCheckBox))
