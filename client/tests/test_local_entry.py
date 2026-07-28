import pytest

from client.app.local_entry import arm_fixture_position_guidance, parse_replay_arguments


def test_replay_speed_defaults_to_real_time_and_accepts_development_override() -> None:
    assert parse_replay_arguments([]).replay_speed == 1.0
    assert parse_replay_arguments(["--replay-speed", "8"]).replay_speed == 8.0


def test_verify_requires_an_explicit_output_directory(tmp_path) -> None:
    with pytest.raises(SystemExit):
        parse_replay_arguments(["--verify"])

    arguments = parse_replay_arguments(["--verify", "--output-dir", str(tmp_path)])
    assert arguments.verify is True
    assert arguments.output_dir == tmp_path


class _Controller:
    def __init__(self) -> None:
        self.observations: list[dict] = []

    def on_position_observation(self, **kwargs) -> None:
        self.observations.append(kwargs)


def test_fixture_position_guidance_rearms_after_every_stage_at_replay_speed() -> None:
    controller = _Controller()
    scheduled: list[tuple[int, object]] = []

    arm_fixture_position_guidance(
        controller,
        replay_speed=2.0,
        schedule=lambda delay, callback: scheduled.append((delay, callback)),
    )

    assert controller.observations == [
        {"now_seconds": 0, "contact_ready": True, "in_valid_area": True}
    ]
    assert scheduled[0][0] == 1500
    scheduled[0][1]()
    assert controller.observations[-1] == {
        "now_seconds": 3,
        "contact_ready": True,
        "in_valid_area": True,
    }
