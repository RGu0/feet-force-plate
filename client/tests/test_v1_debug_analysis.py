from client.app.fixture_replay import FixtureReplaySource
from client.local_analysis.v1_debug import V1ReplayDebugProcessor, analyze_v1_replay


def test_v1_debug_analysis_uses_all_four_stages_without_publishing_risk_score() -> None:
    source = FixtureReplaySource.from_repository()
    result = analyze_v1_replay({stage_id: tuple(source.frames_for(stage_id)) for stage_id in source.stage_ids})

    assert result.status == "DEBUG_READY"
    assert result.score is None
    assert result.risk_level is None
    assert len(result.metrics) == 16
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

    V1ReplayDebugProcessor(source, report_sink=sink).process("session-42")

    assert sink.saved[0][0] == "session-42"
    assert len(sink.saved[0][1].metrics) == 16
