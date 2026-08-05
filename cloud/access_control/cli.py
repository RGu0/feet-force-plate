"""Provider-only seed access bootstrap and lifecycle CLI."""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
import getpass
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import sys
from typing import Any
from uuid import uuid4

from cloud.api.seed import SeedSettings, build_seed_app
from shared.contracts.access_control import (
    InventoryBatchCreateRequest,
    PlatformLoginRequest,
    PlatformRole,
    ProvisionTenantRequest,
)

from .platform_service import normalize_login_name


def _json_input(path: str) -> dict[str, Any]:
    if path == "-":
        return json.loads(sys.stdin.read())
    return json.loads(Path(path).read_text())


def _safe_print(value: dict[str, Any]) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def _password(payload: dict[str, Any], prompt: str) -> str:
    value = payload.pop("platform_password", None)
    return str(value) if value is not None else getpass.getpass(prompt)


async def _bootstrap_owner(args: argparse.Namespace, app: Any) -> None:
    password = getpass.getpass("New Platform owner password: ")
    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        raise ValueError("password confirmation does not match")
    response = await app.state.services.platform_identities.bootstrap_owner(
        login_name=args.login_name, display_name=args.display_name, password=password
    )
    _safe_print(
        {
            "platform_identity_id": str(response.platform_identity_id),
            "roles": [role.value for role in response.roles],
            "status": "created",
        }
    )


async def _provision_tenant(args: argparse.Namespace, app: Any) -> None:
    if args.json_input:
        payload = _json_input(args.json_input)
        platform_login = str(payload.pop("platform_login"))
        platform_password = _password(payload, "Platform password: ")
        request = ProvisionTenantRequest.model_validate(payload)
    else:
        request = ProvisionTenantRequest(
            tenant_name=args.tenant_name,
            account_name=args.account_name,
            hardware_id=args.hardware_id,
            license_period_months=args.license_period_months,
        )
        platform_login = args.platform_login
        platform_password = getpass.getpass("Platform password: ")
        print(
            f"Tenant={request.tenant_name}; account={request.account_name}; "
            f"hardware={request.hardware_id}; months={request.license_period_months}"
        )
        if input("Type PROVISION to continue: ").strip() != "PROVISION":
            raise RuntimeError("provisioning cancelled")
    login = await app.state.services.platform_identities.login(
        PlatformLoginRequest(login_name=platform_login, password=platform_password)
    )
    context = app.state.services.platform_identities.verify_access_token(login.access_token)
    response = await app.state.services.platform_access.provision_tenant(context, request)
    # The activation code is intentionally emitted exactly once in this response.
    _safe_print(response.model_dump(mode="json"))


async def _rotate_platform_role(args: argparse.Namespace, app: Any) -> None:
    payload = _json_input(args.json_input) if args.json_input else {
        "platform_login": args.platform_login,
        "target_login": args.target_login,
        "roles": args.roles,
    }
    password = _password(payload, "Platform owner password: ")
    owner_login = await app.state.services.platform_identities.login(
        PlatformLoginRequest(login_name=str(payload["platform_login"]), password=password)
    )
    owner = app.state.services.platform_identities.verify_access_token(owner_login.access_token)
    if PlatformRole.OWNER not in owner.roles:
        raise PermissionError("only Platform owner can rotate roles")
    roles = tuple(PlatformRole(value) for value in payload["roles"])
    if not roles or len(set(roles)) != len(roles):
        raise ValueError("roles must be non-empty and unique")
    settings: SeedSettings = app.state.seed_settings
    target_digest = hmac.new(
        settings.platform_login_hmac_key.encode(),
        normalize_login_name(str(payload["target_login"])).encode(),
        hashlib.sha256,
    ).digest()
    platform_pool = app.state.seed_pools[2]
    async with platform_pool.acquire() as connection:
        async with connection.transaction():
            target_id = await connection.fetchval(
                "SELECT platform_identity_id FROM iam.platform_identities "
                "WHERE login_name_hmac=$1 FOR UPDATE", target_digest,
            )
            if target_id is None:
                raise ValueError("target Platform identity does not exist")
            await connection.execute(
                "UPDATE iam.platform_identity_role_bindings SET valid_to=now() "
                "WHERE platform_identity_id=$1 AND valid_to IS NULL", target_id,
            )
            for role in roles:
                await connection.execute(
                    """INSERT INTO iam.platform_identity_role_bindings
                       (platform_identity_role_binding_id,platform_identity_id,
                        platform_role_id,valid_from,created_at)
                       SELECT gen_random_uuid(),$1,platform_role_id,now(),now()
                       FROM iam.platform_roles WHERE role_name=$2""",
                    target_id, role.value,
                )
    _safe_print(
        {"platform_identity_id": str(target_id), "roles": [role.value for role in roles],
         "status": "rotated"}
    )


async def _inspect_license(args: argparse.Namespace, app: Any) -> None:
    from uuid import UUID

    row = await app.state.access_repository.license(UUID(args.license_id))
    _safe_print(
        {
            "tenant_id": str(row.tenant_id), "license_id": str(row.license_id),
            "status": row.status.value, "enabled_features": list(row.enabled_features),
            "valid_from": row.valid_from.isoformat(), "valid_until": row.valid_until.isoformat(),
            "version": row.version,
        }
    )


async def _create_sales_inventory(args: argparse.Namespace, app: Any) -> None:
    request = InventoryBatchCreateRequest(quantity=args.quantity)
    password = getpass.getpass("Platform Operations password: ")
    login = await app.state.services.platform_identities.login(
        PlatformLoginRequest(login_name=args.platform_login, password=password)
    )
    context = app.state.services.platform_identities.verify_access_token(login.access_token)
    if not {PlatformRole.OWNER, PlatformRole.OPERATIONS}.intersection(context.roles):
        raise PermissionError("Platform role cannot create sales inventory")

    output = Path(args.output).expanduser().resolve()
    if output.exists():
        raise FileExistsError("delivery output already exists")
    output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    now = datetime.now(UTC)
    batch_id = uuid4()
    codes = [secrets.token_urlsafe(32) for _ in range(request.quantity)]
    hmac_key = app.state.seed_settings.activation_hmac_key.encode("utf-8")
    output_created = False
    try:
        async with app.state.seed_pools[2].acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    """INSERT INTO sales.inventory_batches
                       (inventory_batch_id,model,license_period_months,quantity,created_at)
                       VALUES ($1,$2,$3,$4,$5)""",
                    batch_id, request.model, request.license_period_months, request.quantity, now,
                )
                asset_serials: list[str] = []
                for code in codes:
                    sequence = await connection.fetchval(
                        "SELECT nextval('sales.device_asset_serial_sequence')"
                    )
                    asset_serial = f"FFP-DP4864-{int(sequence):06d}"
                    asset_serials.append(asset_serial)
                    device_inventory_id = uuid4()
                    await connection.execute(
                        """INSERT INTO sales.device_inventory
                           (device_inventory_id,inventory_batch_id,asset_serial,status)
                           VALUES ($1,$2,$3,'IN_STOCK')""",
                        device_inventory_id, batch_id, asset_serial,
                    )
                    digest = hmac.new(hmac_key, code.encode("utf-8"), hashlib.sha256).digest()
                    await connection.execute(
                        """INSERT INTO sales.license_inventory
                           (license_inventory_id,inventory_batch_id,device_inventory_id,
                            activation_code_hmac,status)
                           VALUES ($1,$2,$3,$4,'UNUSED')""",
                        uuid4(), batch_id, device_inventory_id, digest,
                    )
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        descriptor = os.open(output, flags, 0o600)
        output_created = True
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(
                {"batch_id": str(batch_id), "asset_serials": asset_serials, "license_codes": codes},
                handle, ensure_ascii=False, separators=(",", ":"),
            )
            handle.write("\n")
        output.chmod(0o600)
    except Exception:
        if output_created:
            output.unlink()
        raise
    _safe_print({
        "batch_id": str(batch_id), "quantity": request.quantity,
        "license_period_months": request.license_period_months,
        "delivery_file": "written", "codes_printed": False,
    })


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="FeetForcePlate seed access administration")
    commands = parser.add_subparsers(dest="command", required=True)
    owner = commands.add_parser("bootstrap-platform-owner")
    owner.add_argument("--login-name", required=True)
    owner.add_argument("--display-name", required=True)

    provision = commands.add_parser("provision-tenant")
    provision.add_argument("--json-input")
    provision.add_argument("--platform-login")
    provision.add_argument("--tenant-name")
    provision.add_argument("--account-name")
    provision.add_argument("--hardware-id")
    provision.add_argument("--license-period-months", type=int, choices=(6, 12))

    rotate = commands.add_parser("rotate-platform-role")
    rotate.add_argument("--json-input")
    rotate.add_argument("--platform-login")
    rotate.add_argument("--target-login")
    rotate.add_argument("--roles", nargs="+")

    inspect = commands.add_parser("inspect-license")
    inspect.add_argument("--license-id", required=True)
    inventory = commands.add_parser("create-sales-inventory")
    inventory.add_argument("--platform-login", required=True)
    inventory.add_argument("--quantity", type=int, required=True)
    inventory.add_argument("--output", required=True)
    return parser


async def _run(args: argparse.Namespace) -> None:
    app = await build_seed_app(SeedSettings.from_env())
    try:
        if args.command == "bootstrap-platform-owner":
            await _bootstrap_owner(args, app)
        elif args.command == "provision-tenant":
            await _provision_tenant(args, app)
        elif args.command == "rotate-platform-role":
            await _rotate_platform_role(args, app)
        elif args.command == "create-sales-inventory":
            await _create_sales_inventory(args, app)
        else:
            await _inspect_license(args, app)
    finally:
        for pool in app.state.seed_pools:
            await pool.close()


def main() -> None:
    asyncio.run(_run(_parser().parse_args()))


if __name__ == "__main__":
    main()
