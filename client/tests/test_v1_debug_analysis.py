from client.app.fixture_replay import FixtureReplaySource
from client.local_analysis.models import LocalAnalysisResult, LocalQualityStatus
from client.local_analysis.v1_debug import V1ReplayDebugProcessor, analyze_v1_replay


def test_v1_debug_analysis_returns_versioned_local_result_without_customer_metrics() -> None:
    source = FixtureReplaySource.from_repository()
    result = analyze_v1_replay({stage_id: tuple(source.frames_for(stage_id)) for stage_id in source.stage_ids})

    assert isinstance(result, LocalAnalysisResult)
    assert result.result_version == 1
    assert result.algorithm_version == "v1-replay-debug/1.0.0"
    assert result.protocol_id == "standard-static-bilateral"
    assert result.protocol_version == "v1-replay-debug/1.0.0"
    assert result.source_frame_count == 1_658
    assert result.quality_status is LocalQualityStatus.VALID
    assert result.customer_metrics == ()
    assert len(result.internal_metrics) == 16
    assert set(result.withheld_reason_map.values()) == {
        "REPLAY_DEBUG_NOT_CUSTOMER_VALIDATED"
    }
    assert result.relative_heatmap


class _AnalysisSink:
    def __init__(self) -> None:
        self.saved = []

    def save_analysis_result(self, session_id, result) -> None:
        self.saved.append((session_id, result))

    def save_report(self, report) -> None:
        _ = report


def test_v1_debug_processor_persists_reproducible_analysis_before_report() -> None:
    source = FixtureReplaySource.from_repository()
    sink = _AnalysisSink()

    outcome = V1ReplayDebugProcessor(source, report_sink=sink).process("session-42")

    assert sink.saved[0][0] == "session-42"
    saved = sink.saved[0][1]
    assert isinstance(saved, LocalAnalysisResult)
    assert saved.customer_metrics == ()
    assert len(saved.internal_metrics) == 16
    assert outcome.report is not None
    assert outcome.report.protocol_id == saved.protocol_id
    assert outcome.report.protocol_version == saved.protocol_version
    assert len(outcome.report.metrics) == 16
