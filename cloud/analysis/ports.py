from __future__ import annotations

from typing import Protocol

from cloud.analysis.models import (
    AnalysisRun,
    AnalysisRunKey,
    PublishedEvent,
    QualityAssessment,
    RawSession,
    SessionIngestedEvent,
)


class RawSessionLoader(Protocol):
    def load(self, event: SessionIngestedEvent) -> RawSession: ...


class CloudQualityAssessor(Protocol):
    def assess(self, raw_session: RawSession) -> QualityAssessment: ...


class AnalysisRepository(Protocol):
    def get(self, key: AnalysisRunKey) -> AnalysisRun | None: ...

    def reserve(self, run: AnalysisRun) -> AnalysisRun: ...

    def save(self, run: AnalysisRun) -> None: ...


class AnalysisEventPublisher(Protocol):
    def publish(self, event: PublishedEvent) -> None: ...
