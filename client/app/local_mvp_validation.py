"""Automated, local-only evidence capture for the four-stage replay MVP."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import time

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QCheckBox, QLineEdit

from client.app.fixture_replay import FixtureReplaySource
from client.app.local_entry import LocalReplayRuntime, build_local_replay_runtime
from client.app.pages import PageId
from client.reporting.models import BasicReportDocument
from client.workflow.state_machine import ScreeningStep


@dataclass(frozen=True, slots=True)
class LocalMvpValidationResult:
    exit_code: int
    output_dir: Path
    summary_path: Path | None


class _LocalMvpValidationRun:
    _SCREENSHOTS = (
        "01-preflight.png",
        "02-stage-1.png",
        "03-stage-2.png",
        "04-stage-3.png",
        "05-stage-4.png",
        "06-report-preview.png",
    )

    def __init__(self, *, output_dir: Path, replay_speed: float) -> None:
        self._output_dir = output_dir
        self._replay_speed = replay_speed
        self._runtime: LocalReplayRuntime | None = None
        self._loop = QEventLoop()
        self._exit_code = 1
        self._finished = False
        self._stage_index = 0
        self._deadline = 0.0

    def run(self) -> LocalMvpValidationResult:
        try:
            self._prepare_output_directory()
            self._runtime = build_local_replay_runtime(
                replay_speed=self._replay_speed,
                storage_root=self._output_dir / "local-state",
                export_destination=self._output_dir / "report.pdf",
            )
            if not isinstance(self._runtime.source, FixtureReplaySource):
                raise RuntimeError("回放 fixture 不可用，无法开始本机 MVP 验证")
            self._runtime.acquisition.set_callbacks(
                on_progress=lambda seconds: self._controller.on_acquisition_elapsed(seconds),
                on_complete=self._complete_stage,
            )
            self._deadline = time.monotonic() + 30.0
            self._controller.window.show()
            QTimer.singleShot(0, self._start)
            self._loop.exec()
        except Exception as error:
            self._fail(error)
        finally:
            if self._runtime is not None:
                self._runtime.controller.window.close()
        summary_path = self._output_dir / "summary.json"
        return LocalMvpValidationResult(
            exit_code=self._exit_code,
            output_dir=self._output_dir,
            summary_path=summary_path if summary_path.is_file() else None,
        )

    @property
    def _controller(self):
        if self._runtime is None:
            raise RuntimeError("本机 MVP 回放组合未初始化")
        return self._runtime.controller

    @property
    def _source(self) -> FixtureReplaySource:
        if self._runtime is None or not isinstance(self._runtime.source, FixtureReplaySource):
            raise RuntimeError("回放 fixture 不可用")
        return self._runtime.source

    def _prepare_output_directory(self) -> None:
        if self._output_dir.exists() and any(self._output_dir.iterdir()):
            raise ValueError("--output-dir 必须为空目录")
        self._output_dir.mkdir(parents=True, exist_ok=True)

    def _start(self) -> None:
        try:
            self._controller.dispatch("START_NEW_SCREENING")
            identifier = self._controller.window.findChild(
                QLineEdit, "subjectExternalIdInput"
            )
            consent = self._controller.window.findChild(QCheckBox, "requiredConsent")
            if identifier is None or consent is None:
                raise RuntimeError("本机 MVP 验证 UI 缺少建档或授权控件")
            identifier.setText("MVP-REPLAY-0001")
            self._controller.dispatch("LOOKUP_SUBJECT")
            self._controller.dispatch("CONFIRM_SUBJECT")
            self._controller.dispatch("SKIP_PROFILE")
            consent.setChecked(True)
            self._controller.dispatch("CONFIRM_CONSENT")
            self._wait_for(
                lambda: self._controller._coordinator.state.step is ScreeningStep.PREFLIGHT
                and self._controller._coordinator.state.preflight_ready,
                self._preflight_ready,
            )
        except Exception as error:
            self._fail(error)

    def _preflight_ready(self) -> None:
        self._capture(self._SCREENSHOTS[0])
        self._controller.dispatch("ENTER_POSITION")
        self._wait_for(
            lambda: self._controller._coordinator.state.step
            is ScreeningStep.POSITION_GUIDANCE,
            self._start_stage,
        )

    def _start_stage(self) -> None:
        now_seconds = float(self._stage_index * 10)
        self._controller.on_position_observation(
            now_seconds=now_seconds,
            contact_ready=True,
            in_valid_area=True,
        )
        self._controller.on_position_observation(
            now_seconds=now_seconds + 3,
            contact_ready=True,
            in_valid_area=True,
        )
        self._controller.dispatch("START_ACQUISITION")
        if self._controller._coordinator.state.step is not ScreeningStep.ACQUIRING:
            raise RuntimeError("回放阶段未进入采集状态")
        self._capture(self._SCREENSHOTS[self._stage_index + 1])

    def _complete_stage(self) -> None:
        try:
            self._controller.on_acquisition_elapsed(20)
            if self._stage_index < 3:
                self._stage_index += 1
                self._wait_for(
                    lambda: self._controller._coordinator.state.step
                    is ScreeningStep.POSITION_GUIDANCE,
                    self._start_stage,
                )
                return
            self._wait_for(
                lambda: self._controller._coordinator.state.step
                is ScreeningStep.BASIC_REPORT,
                self._report_ready,
            )
        except Exception as error:
            self._fail(error)

    def _report_ready(self) -> None:
        try:
            state = self._controller._coordinator.state
            if state.report_id is None or state.report_version is None:
                raise RuntimeError("回放完成后未生成本地调试报告")
            if self._runtime is None:
                raise RuntimeError("本机 MVP 回放组合未初始化")
            if self._runtime.store.db.execute(
                "SELECT COUNT(*) FROM replay_stage_completions"
            ).fetchone()[0] != 4:
                raise RuntimeError("四阶段回放记录不完整")
            self._controller.dispatch("VIEW_BASIC_REPORT")
            self._capture(self._SCREENSHOTS[-1])
            self._controller.dispatch("EXPORT_PDF")
            pdf_path = self._output_dir / "report.pdf"
            if not pdf_path.is_file() or pdf_path.stat().st_size == 0:
                raise RuntimeError("本地调试报告 PDF 未生成")
            self._controller.window.present_records(self._runtime.store.recent_records())
            self._controller.dispatch(f"OPEN_REPORT:{state.report_id}:{state.report_version}")
            if self._controller.window.current_page_id is not PageId.REPORT_PREVIEW:
                raise RuntimeError("本地历史记录未能重新打开调试报告")
            report = BasicReportDocument.from_json(
                self._runtime.store.load_report(state.report_id, state.report_version)
            )
            self._write_success_summary(state.session_id, report)
            self._exit_code = 0
            self._finish()
        except Exception as error:
            self._fail(error)

    def _wait_for(self, predicate, on_ready) -> None:
        if self._finished:
            return
        if predicate():
            QTimer.singleShot(0, on_ready)
            return
        if time.monotonic() >= self._deadline:
            self._fail(RuntimeError("本机 MVP 回放验证超时"))
            return
        QTimer.singleShot(5, lambda: self._wait_for(predicate, on_ready))

    def _capture(self, filename: str) -> None:
        QApplication.processEvents()
        destination = self._output_dir / filename
        if not self._controller.window.grab().save(str(destination), "PNG"):
            raise RuntimeError(f"无法保存本机 MVP UI 截图：{filename}")

    def _write_success_summary(
        self, session_id: str | None, report: BasicReportDocument
    ) -> None:
        if session_id is None:
            raise RuntimeError("本机 MVP 回放缺少会话标识")
        stage_counts = {
            stage_id: sum(1 for _ in self._source.frames_for(stage_id))
            for stage_id in self._source.stage_ids
        }
        payload = {
            "schema_version": "local-mvp-validation/1",
            "status": "PASSED",
            "local_only": True,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "fixture": {
                "sha256": self._source.fixture_sha256,
                "frame_count": sum(stage_counts.values()),
                "stage_frame_counts": stage_counts,
                "raw_matrices_included": False,
            },
            "stage_ids": list(self._source.stage_ids),
            "algorithm_status": "DEBUG_READY",
            "report": {
                "report_id": report.report_id,
                "version": report.version,
                "kind": report.kind,
                "pdf": "report.pdf",
            },
            "artifacts": [*self._SCREENSHOTS, "report.pdf", "summary.json"],
        }
        self._write_summary(payload)

    def _fail(self, error: Exception) -> None:
        if self._finished:
            return
        if self._runtime is not None:
            try:
                self._capture("failure.png")
            except Exception:
                pass
        try:
            self._write_summary(
                {
                    "schema_version": "local-mvp-validation/1",
                    "status": "FAILED",
                    "local_only": True,
                    "error": str(error),
                }
            )
        finally:
            self._exit_code = 1
            self._finish()

    def _write_summary(self, payload: dict[str, object]) -> None:
        (self._output_dir / "summary.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def _finish(self) -> None:
        self._finished = True
        if self._loop.isRunning():
            self._loop.exit(self._exit_code)


def run_local_mvp_validation(
    *, output_dir: Path, replay_speed: float
) -> LocalMvpValidationResult:
    """Run the entire local fixture workflow without a network dependency."""

    QApplication.instance() or QApplication(["feet-force-plate-local-mvp"])
    return _LocalMvpValidationRun(
        output_dir=output_dir.resolve(), replay_speed=replay_speed
    ).run()
