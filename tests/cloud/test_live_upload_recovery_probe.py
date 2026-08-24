from __future__ import annotations

import importlib.util
from pathlib import Path
from uuid import uuid4

import pytest

from client.sync.persistent_upload import UploadRetryable


def _probe_module():
    path = (
        Path(__file__).resolve().parents[2]
        / "scripts"
        / "run_ray269_live_upload_recovery.py"
    )
    spec = importlib.util.spec_from_file_location("live_upload_recovery", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _CompletingClient:
    def __init__(self) -> None:
        self.completed = False

    def complete_session(self, *args, **kwargs):
        self.completed = True
        return "accepted"

    def create_subject(self, *args, **kwargs):
        return "accepted"


def test_response_loss_wrapper_preserves_a_completed_server_write_for_restart() -> None:
    module = _probe_module()
    client = _CompletingClient()
    wrapper = module._ResponseLossAfterCompletion(client)

    with pytest.raises(UploadRetryable):
        wrapper.complete_session("token", "session", "manifest", "key")

    assert client.completed is True
    assert wrapper.server_completion_observed is True


def test_response_loss_wrapper_tracks_only_the_current_operation_name() -> None:
    module = _probe_module()
    wrapper = module._ResponseLossAfterCompletion(_CompletingClient())

    wrapper.create_subject("token", "subject", "key")

    assert wrapper.last_operation == "create_subject"


def test_recovery_evidence_is_boolean_only() -> None:
    module = _probe_module()

    assert module._evidence() == {
        "schema_version": "ray269-live-upload-recovery/1",
        "offline_queue_persisted": True,
        "server_completed_before_local_confirmation": True,
        "restart_confirmed_without_duplicate_mutation": True,
        "secrets_or_identifiers_included": False,
    }


def test_synthetic_consent_matches_the_real_cloud_contract() -> None:
    module = _probe_module()
    subject_id = uuid4()

    consent = module._synthetic_consent(subject_id)

    assert consent.subject_uuid == subject_id
    assert consent.evidence_type == "OPERATOR_CONFIRMED"
    assert len(consent.terminal_signature) >= 16


def test_synthetic_segment_uses_the_supported_five_second_window() -> None:
    module = _probe_module()

    assert module._synthetic_segment_duration_seconds() == 5.0


def test_failed_recovery_evidence_keeps_only_a_known_stage_and_outcome() -> None:
    module = _probe_module()

    assert module._failure_evidence(
        "completion_response_loss", "BLOCKED", "E-SYN-400", "create_session"
    ) == {
        "schema_version": "ray269-live-upload-recovery/1",
        "failure_category": "recovery_contract",
        "failure_stage": "completion_response_loss",
        "failure_outcome": "BLOCKED",
        "failure_error_code": "E-SYN-400",
        "failure_operation": "create_session",
        "secrets_or_identifiers_included": False,
    }
