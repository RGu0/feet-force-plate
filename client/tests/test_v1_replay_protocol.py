from client.workflow.protocol import default_standard_protocol


def test_default_protocol_describes_the_four_required_v1_replay_stages() -> None:
    protocol = default_standard_protocol()

    assert protocol.acquisition_duration_seconds == 80
    assert [stage.stage_id for stage in protocol.stages] == [
        "BILATERAL_EYES_OPEN",
        "BILATERAL_EYES_CLOSED",
        "SEMI_TANDEM_LEFT_FORWARD",
        "SEMI_TANDEM_RIGHT_FORWARD",
    ]
    assert [stage.duration_seconds for stage in protocol.stages] == [20, 20, 20, 20]
    assert protocol.snapshot().stage_ids == tuple(
        stage.stage_id for stage in protocol.stages
    )
