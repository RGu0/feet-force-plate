"""Explicit operator verification for a blocked offline subject upload."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QVBoxLayout, QWidget,
)

from client.sync.subject_recovery import RecoveryPreview, SubjectRecoveryService


class SubjectRecoveryDialog(QDialog):
    def __init__(self, service: SubjectRecoveryService, parent: QWidget) -> None:
        super().__init__(parent)
        self._service = service
        self._preview: RecoveryPreview | None = None
        self.setWindowTitle("待传档案受控核对")
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        intro = QLabel(
            "仅处理已完成的本地检测。请先核对机构原始档案，确认云端与本地确属同一人。"
            "若无法确认，请关闭窗口，数据会留在本机。"
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self._sessions = QComboBox()
        self._sessions.setAccessibleName("选择待核对的本地检测")
        self._sessions.currentIndexChanged.connect(self._invalidate_preview)
        layout.addWidget(self._sessions)
        self._load = QPushButton("查询云端档案")
        self._load.clicked.connect(self._prepare)
        layout.addWidget(self._load)
        self._comparison = QLabel("尚未查询")
        self._comparison.setWordWrap(True)
        layout.addWidget(self._comparison)
        self._same_person = QCheckBox("我已核对原始档案，确认本地与云端是同一人")
        self._necessary = QCheckBox("本人或有权代理人已重新同意必要的筛查数据处理与补传")
        self._research = QCheckBox("同时同意算法研究用途（可选）")
        for checkbox in (self._same_person, self._necessary, self._research):
            checkbox.setEnabled(False)
            layout.addWidget(checkbox)
        actions = QHBoxLayout()
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        self._confirm = QPushButton("确认核对、签发新同意并补传")
        self._confirm.setEnabled(False)
        self._confirm.clicked.connect(self._authorize)
        actions.addWidget(cancel)
        actions.addWidget(self._confirm)
        layout.addLayout(actions)
        self._same_person.toggled.connect(self._update_confirm)
        self._necessary.toggled.connect(self._update_confirm)
        self._load_candidates()

    def _load_candidates(self) -> None:
        self._sessions.clear()
        try:
            candidates = self._service.candidates()
        except Exception:
            self._comparison.setText("无法读取待传记录；请联系技术支持。")
            self._load.setEnabled(False)
            return
        for candidate in candidates:
            label = (
                f"{candidate.started_at.astimezone().strftime('%m-%d %H:%M')}"
                f" · 机构编号 {candidate.local_identifier_masked}"
            )
            self._sessions.addItem(label, candidate.session_id)
        self._load.setEnabled(bool(candidates))
        if not candidates:
            self._comparison.setText("当前没有可受控核对的待传记录。")

    def _prepare(self) -> None:
        session_id = self._sessions.currentData()
        if session_id is None:
            return
        self._invalidate_preview()
        try:
            preview = self._service.prepare(session_id)
        except Exception:
            self._comparison.setText("云端核对未完成；待传数据仍保留在本机。")
            return
        self._preview = preview
        self._comparison.setText(
            f"本地机构编号：{preview.local_identifier_masked}\n"
            f"云端机构编号：{preview.cloud_identifier_masked or '未提供掩码'}\n"
            "请结合机构原始档案核对本人；仅凭编号相似不得确认。"
        )
        for checkbox in (self._same_person, self._necessary, self._research):
            checkbox.setChecked(False)
            checkbox.setEnabled(
                checkbox is not self._research or preview.research_available
            )

    def _invalidate_preview(self) -> None:
        self._preview = None
        for checkbox in (self._same_person, self._necessary, self._research):
            checkbox.setChecked(False)
            checkbox.setEnabled(False)
        self._confirm.setEnabled(False)

    def _update_confirm(self) -> None:
        self._confirm.setEnabled(
            self._preview is not None
            and self._same_person.isChecked()
            and self._necessary.isChecked()
        )

    def _authorize(self) -> None:
        preview = self._preview
        if preview is None:
            return
        self._confirm.setEnabled(False)
        try:
            self._service.authorize(
                preview,
                same_person_confirmed=self._same_person.isChecked(),
                necessary_processing_accepted=self._necessary.isChecked(),
                research_accepted=self._research.isChecked(),
            )
        except Exception:
            QMessageBox.warning(
                self, "核对未完成", "云端档案或本地状态已变化；未签发新同意，请重新核对。"
            )
            self._preview = None
            self._load_candidates()
            return
        QMessageBox.information(
            self, "已记录新同意", "原始数据保持在本机，后台将继续补传；可稍后查看同步状态。"
        )
        self.accept()
