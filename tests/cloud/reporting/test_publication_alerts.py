import logging
from threading import Event
from unittest.mock import Mock

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
    first = monitor.watch_publication("A")
    second = monitor.watch_publication("A")
    clock[0] = 5
    for timer in timers[:]:
        timer.fire()
    assert sum("status=OPEN" in s for s in caplog.messages) == 1
    for tenant in ("A", "B"):
        monitor.watch_publication(tenant).finish(published=True)
    first.finish(published=True)
    assert not any("status=RESOLVED" in s for s in caplog.messages)
    second.finish(published=True)
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
        deadline = monitor.watch_publication("A")
        assert observed.wait(3)
        deadline.finish(published=True)
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
    failed = monitor.watch_publication("A")
    clock[0] = 6
    failed.finish(published=False)
    monitor.watch_publication("A").finish(published=False)
    assert len(caplog.messages) == 1
    assert "ffp-report-publication-delayed-v1 status=OPEN" in caplog.text
    assert "private" not in caplog.text
    metrics.observe.assert_not_called()
