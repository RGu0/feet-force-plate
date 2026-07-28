from pathlib import Path

from client.app.fixture_replay import FixtureReplayBootstrap, FixtureReplaySource


def test_fixture_replay_validates_and_exposes_each_v1_stage() -> None:
    source = FixtureReplaySource.from_repository(Path(__file__))

    assert source.stage_ids == (
        "BILATERAL_EYES_OPEN", "BILATERAL_EYES_CLOSED",
        "SEMI_TANDEM_LEFT_FORWARD", "SEMI_TANDEM_RIGHT_FORWARD",
    )
    frames = tuple(source.frames_for("BILATERAL_EYES_OPEN"))
    assert len(frames) == 414
    assert frames[0].values.shape == (48, 64)
    assert not frames[0].values.flags.writeable


def test_invalid_fixture_is_exposed_as_a_safe_preflight_failure() -> None:
    bootstrap = FixtureReplayBootstrap(
        lambda: (_ for _ in ()).throw(ValueError("回放数据完整性校验失败"))
    )

    failure = bootstrap.preflight_summary().first_failure

    assert failure is not None
    assert failure.error_code == "E-FIX-001"
    assert failure.operator_message == "回放调试数据不可用，请联系技术支持"
    assert bootstrap.source is None
