from contextlib import ExitStack
import logging
from threading import Event
from time import monotonic
from unittest.mock import Mock

import pytest

from cloud.reporting import alerts


def test_deadline_opens_during_unfinished_publication_and_recovers_per_tenant(monkeypatch, caplog):
    timers = []

    def new_timer(interval, callback):
        timer = Mock(interval=interval, fire=callback)
        timers.append(timer)
        return timer

    monkeypatch.setattr(alerts, "Timer", new_timer)
    clock = [0.0]
    monkeypatch.setattr(alerts, "monotonic", lambda: clock[0])
    monitor = alerts.ReportPublicationAlerts(delay_seconds=5)
    caplog.set_level(logging.INFO, logger="cloud.reporting.alerts")
    with ExitStack() as delayed:
        delayed.enter_context(monitor.publishing("A", 0))
        delayed.enter_context(monitor.publishing("A", 0))
        clock[0] = 5
        for timer in timers[:]:
            timer.fire()
        assert sum("status=OPEN" in s for s in caplog.messages) == 1
        for tenant in ("A", "B"):
            with monitor.publishing(tenant, 5):
                pass
        assert not any("status=RESOLVED" in s for s in caplog.messages)
    with monitor.publishing("A", 5):
        pass
    assert sum("status=RESOLVED" in s for s in caplog.messages) == 1
    for timer in timers:
        timer.cancel.assert_called_once()
        timer.fire()  # Cancellation can race a timer which has already woken up.
    assert len(caplog.messages) == 2


def test_real_timer_reports_a_stalled_attempt_before_it_returns(caplog):
    observed = Event()

    class Notify(logging.Handler):
        def emit(self, record):
            if "ffp-report-publication-delayed-v1" in record.getMessage():
                observed.set()

    handler = Notify()
    logger = logging.getLogger("cloud.reporting.alerts")
    logger.addHandler(handler)
    try:
        monitor = alerts.ReportPublicationAlerts(delay_seconds=0.02)
        with monitor.publishing("A", monotonic()):
            assert observed.wait(3)
        assert "status=OPEN" in caplog.text
    finally:
        logger.removeHandler(handler)


def test_failed_publication_does_not_count_as_recovery_or_a_pdf_failure(monkeypatch, caplog):
    metrics = Mock()
    monitor = alerts.ReportPublicationAlerts(delay_seconds=5, metrics=metrics)
    monkeypatch.setattr(alerts, "Timer", Mock())
    clock = [0]
    monkeypatch.setattr(alerts, "monotonic", lambda: clock[0])
    caplog.set_level(logging.INFO, logger="cloud.reporting.alerts")
    with pytest.raises(RuntimeError):
        with monitor.publishing("A", 0):
            clock[0] = 6
            raise RuntimeError("private publishing error")
    with pytest.raises(RuntimeError):
        with monitor.publishing("A", 6):
            raise RuntimeError("private artifact error")
    assert len(caplog.messages) == 1
    assert "ffp-report-publication-delayed-v1 status=OPEN" in caplog.text
    assert "private" not in caplog.text
    metrics.observe.assert_not_called()
