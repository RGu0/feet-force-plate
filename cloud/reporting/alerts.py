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
        _LOG.log(logging.INFO if incident.status is AlertStatus.RESOLVED else logging.WARNING,
                 "report_alert rule=%s status=%s incident=%s tenant_hash=%s count=%d runbook=%s",
                 incident.rule_id, incident.status.value, incident.incident_id,
                 hashlib.sha256(tenant_id.encode()).hexdigest(), incident.occurrence_count,
                 incident.runbook)

    def _export(self, name: str, value: float) -> None:
        if self._metrics is not None:
            try:
                self._metrics.observe(name, value=value)
            except Exception:
                _LOG.warning("report metric export unavailable")

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

    @contextmanager
    def publishing(self, tenant_id: str, requested_at: float) -> Iterator[None]:
        """Start the deadline only when the repository admits a new report version."""
        finished = overdue = False

        def deadline() -> None:
            nonlocal overdue
            with self._lock:
                if finished or overdue:
                    return
                overdue = True
                self._overdue[tenant_id] += 1
                self._observe(tenant_id, "report_generation_seconds", self.delay_seconds)

        remaining = self.delay_seconds - (monotonic() - requested_at)
        timer = Timer(max(0, remaining), deadline)
        timer.daemon = True
        try:
            timer.start()
        except RuntimeError:
            # Completion still checks elapsed time if the process cannot create a timer.
            _LOG.warning("report publication deadline timer unavailable")
        published = False
        try:
            yield
            published = True
        finally:
            elapsed = max(0.0, monotonic() - requested_at)
            with self._lock:
                # Also catch a threshold crossing if completion beats the timer callback.
                if elapsed >= self.delay_seconds and not overdue:
                    deadline()
                finished = True
                timer.cancel()
                if overdue:
                    self._overdue[tenant_id] -= 1
                    if not self._overdue[tenant_id]:
                        del self._overdue[tenant_id]
                if published and not overdue and not self._overdue[tenant_id]:
                    self._observe(tenant_id, "report_generation_seconds", elapsed)
            if published:
                self._export("ffp_cloud_complete_publication_seconds_v1", elapsed)


DEFAULT_REPORT_ALERTS = ReportPublicationAlerts()
