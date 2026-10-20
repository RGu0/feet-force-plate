"""Controlled recovery only after a platform-issued identity match receipt."""

from __future__ import annotations

from datetime import UTC, datetime
import os
from pathlib import Path
import threading

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QVBoxLayout, QWidget,
)

from client.sync.subject_recovery import RecoveryPreview, SubjectRecoveryService


class _LookupSignals(QObject):
    completed = Signal(int, object)
    authorization_completed = Signal(int, object)


class SubjectRecoveryDialog(QDialog):
    def __init__(self, service: SubjectRecoveryService, parent: QWidget) -> None:
        super().__init__(parent)
        self._service = service
        self._preview: RecoveryPreview | None = None
        self._lookup_generation = 0
        self._lookup_running = False
        self._authorization_running = False
        self._signals = _LookupSignals(self)
        self._signals.completed.connect(self._lookup_completed)
        self._signals.authorization_completed.connect(self._authorization_completed)
        self.setWindowTitle("待传档案受控核对")
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        intro = QLabel(
            "仅处理已完成的本地检测。请由平台授权人员使用机构原始档案完成受控身份比对。"
            "若无法核实，关闭窗口；数据会留在本机。"
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self._sessions = QComboBox()
        self._sessions.setObjectName("recovery_sessions")
        self._sessions.setAccessibleName("选择待核对的本地检测")
        self._sessions.currentIndexChanged.connect(self._invalidate_preview)
        layout.addWidget(self._sessions)
        self._load = QPushButton("创建或刷新核对案卷")
        self._load.clicked.connect(self._prepare)
        layout.addWidget(self._load)
        self._comparison = QLabel("尚未查询核对案卷")
        self._comparison.setWordWrap(True)
        layout.addWidget(self._comparison)
        self._actor = QComboBox()
        self._actor.setObjectName("recovery_consent_actor")
        self._actor.addItem("请选择重新同意的人", None)
        self._actor.addItem("受试者本人", "SUBJECT_CONFIRMED")
        self._actor.addItem("有权代理人", "REPRESENTATIVE_CONFIRMED")
        self._actor.setEnabled(False)
        self._actor.currentIndexChanged.connect(self._update_confirm)
        layout.addWidget(self._actor)
        self._necessary = QCheckBox("本人或有权代理人已重新同意必要的筛查数据处理与补传")
        self._research = QCheckBox("同时同意算法研究用途（可选）")
        for checkbox in (self._necessary, self._research):
            checkbox.setEnabled(False)
            layout.addWidget(checkbox)
        self._necessary.toggled.connect(self._update_confirm)
        actions = QHBoxLayout()
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        self._confirm = QPushButton("签发新同意并补传")
        self._confirm.setEnabled(False)
        self._confirm.clicked.connect(self._authorize)
        actions.addWidget(cancel)
        actions.addWidget(self._confirm)
        layout.addLayout(actions)
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
        if session_id is None or self._lookup_running:
            return
        self._invalidate_preview()
        self._lookup_running = True
        self._load.setEnabled(False)
        self._comparison.setText("正在读取核对案卷，请稍候。")
        generation = self._lookup_generation

        def worker() -> None:
            try:
                result = self._service.prepare(session_id)
            except Exception as exc:
                result = exc
            self._signals.completed.emit(generation, result)

        threading.Thread(target=worker, name="identity-recovery-lookup", daemon=True).start()

    def _lookup_completed(self, generation: int, result: object) -> None:
        self._lookup_running = False
        self._load.setEnabled(self._sessions.count() > 0)
        if generation != self._lookup_generation:
            return
        if isinstance(result, Exception):
            detail = ""
            if os.environ.get("FEETFORCEPLATE_INTEGRATION_MODE") == "1":
                code = getattr(result, "error_code", None)
                frame = result.__traceback__
                while frame is not None and frame.tb_next is not None:
                    frame = frame.tb_next
                location = (
                    f" @ {Path(frame.tb_frame.f_code.co_filename).name}:{frame.tb_lineno}"
                    if frame is not None else ""
                )
                detail = f"（{type(result).__name__}{f' / {code}' if code else ''}{location}）"
            self._comparison.setText(f"云端核对未完成{detail}；待传数据仍保留在本机。")
            return
        if not isinstance(result, RecoveryPreview):
            self._comparison.setText("核对案卷响应无效；待传数据仍保留在本机。")
            return
        self._preview = result
        case_ref = str(result.case_id).split("-")[0]
        status = {
            "PENDING": "待平台核对", "MATCHED": "已匹配", "DENIED": "未通过",
            "EXPIRED": "回执已过期",
        }.get(result.status, "状态无效")
        self._comparison.setText(
            f"案卷 {case_ref} · {status}\n"
            f"本地机构编号 {result.local_identifier_masked}；"
            "请由平台授权人员完成原始姓名及联系方式比对。"
        )
        matched = self._current_match()
        self._actor.setEnabled(matched)
        self._necessary.setEnabled(matched)
        self._research.setEnabled(matched and result.research_available)
        self._update_confirm()

    def _invalidate_preview(self) -> None:
        self._lookup_generation += 1
        self._preview = None
        self._actor.setCurrentIndex(0)
        self._actor.setEnabled(False)
        for checkbox in (self._necessary, self._research):
            checkbox.setChecked(False)
            checkbox.setEnabled(False)
        self._confirm.setEnabled(False)

    def _current_match(self) -> bool:
        preview = self._preview
        now = getattr(self._service, "now", lambda: datetime.now(UTC))()
        return bool(
            preview is not None and preview.session_id == self._sessions.currentData()
            and preview.status == "MATCHED" and preview.receipt_id is not None
            and preview.platform_ticket_sha256 is not None
            and preview.receipt_expires_at is not None
            and preview.receipt_expires_at > now
        )

    def _update_confirm(self) -> None:
        self._confirm.setEnabled(
            not self._authorization_running and self._current_match() and self._necessary.isChecked()
            and self._actor.currentData() in {"SUBJECT_CONFIRMED", "REPRESENTATIVE_CONFIRMED"}
        )

    def _authorize(self) -> None:
        preview = self._preview
        if preview is None or self._authorization_running or not self._current_match():
            self._update_confirm()
            return
        self._authorization_running = True
        self._load.setEnabled(False)
        self._sessions.setEnabled(False)
        self._actor.setEnabled(False)
        self._necessary.setEnabled(False)
        self._research.setEnabled(False)
        self._confirm.setEnabled(False)
        generation = self._lookup_generation
        evidence_type = self._actor.currentData()
        necessary = self._necessary.isChecked()
        research = self._research.isChecked()

        def worker() -> None:
            try:
                result = self._service.authorize(
                    preview, evidence_type=evidence_type,
                    necessary_processing_accepted=necessary,
                    research_accepted=research,
                )
            except Exception as exc:
                result = exc
            self._signals.authorization_completed.emit(generation, result)

        threading.Thread(target=worker, name="identity-recovery-consent", daemon=True).start()

    def _authorization_completed(self, generation: int, result: object) -> None:
        self._authorization_running = False
        if generation != self._lookup_generation:
            return
        if isinstance(result, Exception):
            QMessageBox.warning(
                self, "核对未完成", "云端案卷或本地状态已变化；未签发新同意，请刷新核对案卷。"
            )
            self._invalidate_preview()
            self._load.setEnabled(self._sessions.count() > 0)
            self._sessions.setEnabled(True)
            return
        QMessageBox.information(
            self, "已记录新同意", "原始数据保持在本机，后台将继续补传；可稍后查看同步状态。"
        )
        self.accept()
