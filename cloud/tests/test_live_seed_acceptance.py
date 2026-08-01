from __future__ import annotations

import json
from pathlib import Path
import subprocess
from uuid import uuid4

import httpx

from scripts.verify_seed_live import AcceptanceState, Api


ROOT = Path(__file__).resolve().parents[2]


def test_acceptance_evidence_excludes_all_replayable_credentials() -> None:
    state = AcceptanceState(
        tenant_id=uuid4(),
        account_name="acceptance-tenant",
        account_password="secret-password-value",
        hardware_id="usb-serial-0123456789abcdef0123",
        hardware_asset_id=uuid4(),
        installation_id=uuid4(),
        session_id=uuid4(),
        platform_login="seed-owner",
        activation_code="secret-activation-code",
        access_token="secret-access-token",
        refresh_token="secret-refresh-token",
    )

    serialized = json.dumps(state.evidence(), sort_keys=True)

    assert state.evidence() == {
        "tenant_provisioned": True,
        "activation_completed": True,
        "session_metadata_created": True,
        "secrets_included": False,
    }
    for secret in (
        state.account_name,
        state.account_password,
        state.hardware_id,
        str(state.hardware_asset_id),
        str(state.installation_id),
        str(state.session_id),
        state.platform_login,
        state.activation_code,
        state.access_token,
        state.refresh_token,
    ):
        assert secret not in serialized


def test_api_waits_for_auth_rate_limit_and_retries_the_request() -> None:
    attempts = 0
    delays: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, request=request)
        return httpx.Response(200, request=request, json={"data": {"status": "ok"}})

    api = Api(
        "https://seed.example:7443",
        Path("unused-with-mock-transport.pem"),
        transport=httpx.MockTransport(handler),
        sleep=delays.append,
    )
    try:
        response, payload = api.request("POST", "/v1/access/login", expected=200)
    finally:
        api.close()

    assert response.status_code == 200
    assert payload == {"status": "ok"}
    assert attempts == 2
    assert delays == [13.0]


def test_acceptance_cleanup_preserves_failed_state_and_removes_successful_state(
    tmp_path: Path,
) -> None:
    script = ROOT / "deploy/aliyun/seed/run-live-acceptance.sh"
    state = tmp_path / "private-state.json"
    restart_marker = tmp_path / "restart-complete"
    state.write_text("private")
    restart_marker.write_text("")

    failed = subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; acceptance_cleanup 1 "$2" "$3"',
            "bash",
            str(script),
            str(state),
            str(restart_marker),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert failed.returncode == 0, failed.stderr
    assert state.read_text() == "private"
    assert restart_marker.exists()
    succeeded = subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; acceptance_cleanup 0 "$2" "$3"',
            "bash",
            str(script),
            str(state),
            str(restart_marker),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert succeeded.returncode == 0, succeeded.stderr
    assert not state.exists()
    assert not restart_marker.exists()


def test_acceptance_resume_phase_is_derived_from_private_state(tmp_path: Path) -> None:
    script = ROOT / "deploy/aliyun/seed/run-live-acceptance.sh"
    state = tmp_path / "private-state.json"
    restart_marker = tmp_path / "restart-complete"

    def phase() -> str:
        result = subprocess.run(
            [
                "bash",
                "-c",
                'source "$1"; acceptance_phase "$2" "$3"',
                "bash",
                str(script),
                str(state),
                str(restart_marker),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    assert phase() == "before-restart"
    state.write_text("private")
    assert phase() == "restart-required"
    restart_marker.write_text("")
    assert phase() == "after-restart"


def test_acceptance_public_junit_path_is_next_to_redacted_json(tmp_path: Path) -> None:
    script = ROOT / "deploy/aliyun/seed/run-live-acceptance.sh"
    evidence = tmp_path / "aliyun-seed-summary.json"
    result = subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; acceptance_public_junit_path "$2"',
            "bash",
            str(script),
            str(evidence),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.strip() == str(tmp_path / "aliyun-seed-summary-postgres.xml")
