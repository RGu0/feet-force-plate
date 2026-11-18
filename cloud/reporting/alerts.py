"""Tenant-scoped operational alerts for cloud report publication."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
import hashlib
import logging
import math
from threading import RLock, Timer
from time import monotonic

from techflex_cloud_foundation.diagnostics import MetricsSink
from techflex_cloud_foundation.server.observability.alerts import (
    AlertEvaluator, AlertRule, AlertSeverity, AlertStatus,
)
from techflex_cloud_foundation.server.observability.events import SLISample


_LOG = logging.getLogger(__name__)
_RUNBOOK = "docs/modules/report-publication-alerts.md"


def _log(level: int, message: str, *args: object) -> None:
    try:
        _LOG.log(level, message, *args)
    except Exception:
        # A broken log handler must not change a report outcome or strand its waiters.
        pass


class ReportPublicationAlerts:
    """Evaluate product rules locally and optionally export the same observations."""

    def __init__(self, *, delay_seconds: float = 300, metrics: MetricsSink | None = None):
        if not math.isfinite(delay_seconds) or delay_seconds <= 0:
            raise ValueError("report publication delay must be finite and positive")
        self.delay_seconds = delay_seconds
        self._metrics = metrics
        cooldown = timedelta(minutes=15)
        self._evaluator = AlertEvaluator((
            AlertRule("ffp-pdf-render-failed-v1", "report_failures", ">=", 1, 1,
                      AlertSeverity.WARNING, cooldown, _RUNBOOK),
            AlertRule("ffp-report-publication-delayed-v1", "report_generation_seconds",
                      ">=", delay_seconds, 1, AlertSeverity.WARNING, cooldown, _RUNBOOK),
        ))
        self._lock = RLock()
        self._overdue: Counter[str] = Counter()
        self._emitted: dict[tuple[str, str], tuple[str, int, AlertStatus]] = {}

    def _observe(self, tenant_id: str, metric: str, value: float) -> None:
        # Called under the monitor lock: the Foundation evaluator is stateful.
        incident = self._evaluator.observe(SLISample(
            metric_name=metric, value=value, observed_at=datetime.now(UTC), tenant_id=tenant_id,
        ))
        if incident is None:
            return
        key = (incident.rule_id, tenant_id)
        revision = (incident.incident_id, incident.occurrence_count, incident.status)
        if self._emitted.get(key) == revision:
            return
        if incident.status is AlertStatus.RESOLVED:
            self._emitted.pop(key, None)
        else:
            self._emitted[key] = revision
        # The default log formatter also carries the incident, without report content.
        _log(logging.INFO if incident.status is AlertStatus.RESOLVED else logging.WARNING,
                 "report_alert rule=%s status=%s incident=%s tenant_hash=%s count=%d runbook=%s",
                 incident.rule_id, incident.status.value, incident.incident_id,
                 hashlib.sha256(tenant_id.encode()).hexdigest(), incident.occurrence_count,
                 incident.runbook)

    def _export(self, name: str, value: float) -> None:
        if self._metrics is not None:
            try:
                self._metrics.observe(name, value=value)
            except Exception:
                _log(logging.WARNING, "report metric export unavailable")

    @contextmanager
    def rendering_pdf(self, tenant_id: str) -> Iterator[None]:
        try:
            yield
        except Exception:
            self._pdf_outcome(tenant_id, 1)
            raise
        else:
            self._pdf_outcome(tenant_id, 0)

    def _pdf_outcome(self, tenant_id: str, failed: int) -> None:
        with self._lock:
            self._observe(tenant_id, "report_failures", failed)
        self._export("ffp_pdf_render_failed_v1", failed)

    def watch_publication(self, tenant_id: str) -> PublicationDeadline:
        return PublicationDeadline(self, tenant_id)


class PublicationDeadline:
    """A logical version retains the same deadline across event delivery retries."""

    def __init__(self, monitor: ReportPublicationAlerts, tenant_id: str):
        self._monitor = monitor
        self._tenant = tenant_id
        self._start = monotonic()
        self._finished = self._late = False
        self._timer = Timer(monitor.delay_seconds, self._deadline)
        self._timer.daemon = True
        try:
            self._timer.start()
        except RuntimeError:
            _log(logging.WARNING, "report publication deadline timer unavailable")

    def _deadline(self) -> None:
        monitor = self._monitor
        with monitor._lock:
            if self._finished or self._late:
                return
            self._late = True
            monitor._overdue[self._tenant] += 1
            monitor._observe(self._tenant, "report_generation_seconds", monitor.delay_seconds)

    def finish(self, *, published: bool) -> None:
        monitor = self._monitor
        elapsed = max(0.0, monotonic() - self._start)
        with monitor._lock:
            if self._finished:
                return
            if elapsed >= monitor.delay_seconds:
                self._deadline()
            self._finished = True
            self._timer.cancel()
            if self._late:
                monitor._overdue[self._tenant] -= 1
                if not monitor._overdue[self._tenant]:
                    del monitor._overdue[self._tenant]
            if published and not monitor._overdue[self._tenant]:
                # No outstanding overdue report; export actual elapsed time separately.
                monitor._observe(self._tenant, "report_generation_seconds", 0)
        if published:
            monitor._export("ffp_cloud_complete_publication_seconds_v1", elapsed)


DEFAULT_REPORT_ALERTS = ReportPublicationAlerts()
