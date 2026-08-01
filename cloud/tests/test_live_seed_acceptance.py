from __future__ import annotations

import json
from uuid import uuid4

from scripts.verify_seed_live import AcceptanceState


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
