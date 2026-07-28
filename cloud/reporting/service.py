from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Callable
from datetime import UTC, datetime

from cloud.analysis.models import AnalysisRun, AnalysisRunStatus
from cloud.reporting.builder import CloudReportBuilder
from cloud.reporting.models import (
    ReportArtifact,
    ReportContext,
    ReportKind,
    ReportPublishedEvent,
    ReportRecord,
    ReportVersion,
)
from cloud.reporting.pdf import MinimalPdfRenderer


class InMemoryArtifactStore:
    def __init__(self) -> None:
        self._objects: dict[str, tuple[str, bytes]] = {}
        self._lock = threading.RLock()

    def put(self, object_key: str, payload: bytes, sha256: str) -> None:
        if hashlib.sha256(payload).hexdigest() != sha256:
            raise ValueError("artifact digest does not match payload")
        with self._lock:
            existing = self._objects.get(object_key)
            if existing is not None and existing != (sha256, payload):
                raise ValueError("immutable artifact key conflict")
            self._objects[object_key] = (sha256, payload)

    def get(self, object_key: str) -> bytes:
        with self._lock:
            return self._objects[object_key][1]

    def count(self) -> int:
        with self._lock:
            return len(self._objects)


class InMemoryReportEventPublisher:
    def __init__(self) -> None:
        self.events: list[ReportPublishedEvent] = []

    def publish(self, event: ReportPublishedEvent) -> None:
        self.events.append(event)


class InMemoryReportRepository:
    def __init__(self) -> None:
        self._reports: dict[tuple[str, str], ReportRecord] = {}
        self._lock = threading.RLock()

    def seed_basic(
        self,
        *,
        tenant_id: str,
        session_id: str,
        report_id: str,
        document_sha256: str,
        artifact_sha256: str,
    ) -> None:
        basic_artifact = ReportArtifact(
            object_key=f"local-reports/{report_id}/v1/{artifact_sha256}.pdf",
            content_type="application/pdf",
            size_bytes=0,
            sha256=artifact_sha256,
            renderer_version="local-basic",
            template_version="local-basic",
        )
        basic = ReportVersion(
            report_id=report_id,
            tenant_id=tenant_id,
            session_id=session_id,
            version_number=1,
            kind=ReportKind.BASIC,
            source_analysis_run_id=None,
            report_schema_version="report-document/1",
            document=None,
            document_sha256=document_sha256,
            artifact=basic_artifact,
            generated_at=datetime.now(UTC),
        )
        with self._lock:
            key = (tenant_id, session_id)
            if key in self._reports:
                raise ValueError("report already exists for this tenant and session")
            self._reports[key] = ReportRecord(
                report_id=report_id,
                tenant_id=tenant_id,
                session_id=session_id,
                latest_version=1,
                versions=(basic,),
            )

    def get_for_session(self, tenant_id: str, session_id: str) -> ReportRecord:
        with self._lock:
            return self._reports[(tenant_id, session_id)]

    def append_cloud_version(
        self,
        *,
        tenant_id: str,
        session_id: str,
        source_analysis_run_id: str,
        build: Callable[[str, int], ReportVersion],
    ) -> tuple[ReportVersion, bool]:
        with self._lock:
            key = (tenant_id, session_id)
            report = self._reports.get(key)
            if report is None:
                raise ValueError("the session report identity must exist before cloud publish")
            for version in report.versions:
                if version.source_analysis_run_id == source_analysis_run_id:
                    return version, False
            version_number = report.latest_version + 1
            version = build(report.report_id, version_number)
            if (
                version.report_id != report.report_id
                or version.version_number != version_number
                or version.kind is not ReportKind.CLOUD_COMPLETE
                or version.source_analysis_run_id != source_analysis_run_id
            ):
                raise ValueError("cloud report version violates the append contract")
            self._reports[key] = ReportRecord(
                report_id=report.report_id,
                tenant_id=tenant_id,
                session_id=session_id,
                latest_version=version_number,
                versions=report.versions + (version,),
            )
            return version, True


class CloudReportService:
    def __init__(
        self,
        *,
        repository: InMemoryReportRepository,
        artifact_store: InMemoryArtifactStore,
        builder: CloudReportBuilder,
        renderer: MinimalPdfRenderer,
        publisher: InMemoryReportEventPublisher,
    ) -> None:
        self.repository = repository
        self.artifact_store = artifact_store
        self.builder = builder
        self.renderer = renderer
        self.publisher = publisher

    def publish(
        self,
        run: AnalysisRun,
        context: ReportContext,
    ) -> ReportVersion | None:
        if run.status is not AnalysisRunStatus.SUCCEEDED:
            return None

        def build(report_id: str, version_number: int) -> ReportVersion:
            document = self.builder.build(
                run=run,
                context=context,
                report_id=report_id,
                version_number=version_number,
            )
            public_json = json.dumps(
                document.to_public_dict(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            document_sha256 = hashlib.sha256(public_json).hexdigest()
            pdf = self.renderer.render(document)
            artifact_sha256 = hashlib.sha256(pdf).hexdigest()
            object_key = (
                f"tenants/{run.key.tenant_id}/reports/{report_id}/"
                f"v{version_number}/{artifact_sha256}.pdf"
            )
            self.artifact_store.put(object_key, pdf, artifact_sha256)
            artifact = ReportArtifact(
                object_key=object_key,
                content_type="application/pdf",
                size_bytes=len(pdf),
                sha256=artifact_sha256,
                renderer_version=self.renderer.renderer_version,
                template_version=self.renderer.template_version,
            )
            return ReportVersion(
                report_id=report_id,
                tenant_id=run.key.tenant_id,
                session_id=run.key.session_id,
                version_number=version_number,
                kind=ReportKind.CLOUD_COMPLETE,
                source_analysis_run_id=run.analysis_run_id,
                report_schema_version=run.report_schema_version,
                document=document,
                document_sha256=document_sha256,
                artifact=artifact,
                generated_at=document.generated_at,
            )

        version, created = self.repository.append_cloud_version(
            tenant_id=run.key.tenant_id,
            session_id=run.key.session_id,
            source_analysis_run_id=run.analysis_run_id,
            build=build,
        )
        if created:
            self.publisher.publish(
                ReportPublishedEvent(
                    event_type="report.published.v1",
                    tenant_id=run.key.tenant_id,
                    report_id=version.report_id,
                    correlation_id=run.correlation_id,
                    version_number=version.version_number,
                    kind=version.kind,
                )
            )
        return version
