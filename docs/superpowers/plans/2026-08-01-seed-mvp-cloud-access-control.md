# Seed MVP Cloud Access Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace terminal-bound authorization with a seed-customer control plane in which the provider provisions a tenant account, License, and physical hardware binding, while preserving tenant isolation, remote License control, new-computer login, and auditable Platform IAM.

**Architecture:** Add a new `cloud.access_control` bounded context beside the legacy terminal enrollment path. Tenant account tokens and Platform tokens have separate issuers, audiences, database roles, and dependencies. The authoritative relationship is tenant account -> License entitlement -> physical hardware binding; a client installation is replaceable and never owns the License. Legacy terminal routes remain compatibility-only and are omitted from the seed production composition.

**Tech Stack:** Python 3.11, Pydantic 2, FastAPI, asyncpg/PostgreSQL 16, `hashlib.scrypt`, Ed25519 from `cryptography`, pytest/httpx.

## Global Constraints

- Run every Python command through `./scripts/local-env.sh`; never create or use a repository-local `.venv`.
- Add migration `cloud/migrations/0003_seed_mvp_access_control.sql`; never rewrite migrations 0001 or 0002.
- Tenant IDs come only from verified tenant access tokens or an explicit, audited Platform grant. Never accept a tenant ID from a request body as authorization.
- Platform identities never receive tenant access tokens. Tenant and Platform token `typ`, `aud`, secrets/keys, dependencies, and database pools stay separate.
- Application database roles must not have `BYPASSRLS`. Tenant transactions call `set_config('app.tenant_id', ..., true)` and reset at transaction end.
- Store password hashes with `hashlib.scrypt`; store activation and refresh credentials only as keyed hashes. Never log raw passwords, activation codes, refresh tokens, patient identity, or License private keys.
- License documents are Ed25519-signed, contain `tenant_id`, `account_id`, `license_id`, `hardware_id`, status/version/validity, and do not contain `terminal_id` or a host fingerprint.
- Online hardware leases have a 10-minute TTL and can be renewed. During a verified offline grace window, the last authorized installation may start a test from the signed License, but global anti-concurrency cannot be proven while multiple clients are offline. Tests and evidence must state this boundary.
- Suspension, revocation, expiry, or offline-limit failure blocks **new** tests only. An active acquisition may finalize safely; historical report viewing and upload remain available.
- Existing `device.licenses`, terminal enrollment, and terminal tokens remain legacy compatibility objects. New code must not read them to decide whether a seed customer can start a test.
- Local test License `FFP-2026-TEST-0001` must never be accepted by cloud activation or production token code.
- Execute this plan first. The client plan may begin after Task 1, but its live API work waits for Task 9; the persistence/deployment plan begins after this plan's completion gate.

---

## Task 1: Define the versioned account, License, and Platform contracts

**Files:**

- Create: `shared/contracts/access_control.py`
- Modify: `shared/contracts/__init__.py`
- Test: `cloud/tests/test_access_control_contracts.py`

- [ ] **Step 1: Write failing contract tests**

Cover these exact invariants:

```python
def test_license_document_binds_account_and_hardware_not_terminal() -> None:
    document = LicenseDocumentV2(
        schema_version="license/2",
        tenant_id=TENANT_ID,
        account_id=ACCOUNT_ID,
        license_id=LICENSE_ID,
        hardware_id="usb-serial-0123456789abcdef0123",
        status=LicenseState.ACTIVE,
        issued_at=NOW,
        valid_from=NOW,
        valid_until=NOW + timedelta(days=365),
        version=1,
    )
    assert "terminal_id" not in document.model_dump()


def test_platform_role_is_not_a_tenant_role() -> None:
    assert set(PlatformRole) == {
        PlatformRole.OWNER,
        PlatformRole.OPERATIONS,
        PlatformRole.SUPPORT,
        PlatformRole.ENGINEER,
    }
```

Also reject blank normalized account names, invalid hardware IDs, duplicate requested roles, non-positive License periods, activation requests without password confirmation, and refresh requests without an installation ID.

- [ ] **Step 2: Run the focused test and confirm import failure**

Run: `./scripts/local-env.sh python -m pytest cloud/tests/test_access_control_contracts.py -q`

Expected: FAIL because `shared.contracts.access_control` does not exist.

- [ ] **Step 3: Implement the contracts**

Define these public types:

```python
class AccountState(StrEnum):
    PENDING_ACTIVATION = "PENDING_ACTIVATION"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class LicenseState(StrEnum):
    PENDING_ACTIVATION = "PENDING_ACTIVATION"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class PlatformRole(StrEnum):
    OWNER = "PLATFORM_OWNER"
    OPERATIONS = "PLATFORM_OPERATIONS"
    SUPPORT = "PLATFORM_SUPPORT"
    ENGINEER = "PLATFORM_ENGINEER"
```

Add `ProvisionTenantRequest/Response`, `ActivateAccountRequest/Response`, `LoginRequest/Response`, `RefreshRequest/Response`, `LicenseDocumentV2`, `SignedLicenseV2`, `LicenseControlRequest`, `HardwareLeaseRequest/Response`, `PlatformLoginRequest/Response`, `SensitiveAccessGrantRequest/Response`, and masked Platform tenant/report summaries. All models use `extra="forbid"` and frozen instances.

- [ ] **Step 4: Run contract and static checks**

Run: `./scripts/local-env.sh python -m pytest cloud/tests/test_access_control_contracts.py -q`

Run: `./scripts/local-env.sh python -m mypy shared/contracts`

Expected: PASS.

- [ ] **Step 5: Commit the contract boundary**

```bash
git add shared/contracts/access_control.py shared/contracts/__init__.py cloud/tests/test_access_control_contracts.py
git commit -m "feat: define seed access control contracts"
```

## Task 2: Add the additive PostgreSQL schema and role grants

**Files:**

- Create: `cloud/migrations/0003_seed_mvp_access_control.sql`
- Modify: `cloud/tests/test_migrations.py`
- Modify: `cloud/tests/test_postgres_tenant_context.py`

- [ ] **Step 1: Write migration shape tests**

Assert migration 0003 creates these authoritative tables:

- `iam.tenant_accounts`
- `iam.account_activation_codes`
- `iam.tenant_refresh_sessions`
- `iam.platform_identities`
- `iam.platform_roles`
- `iam.platform_identity_role_bindings`
- `iam.platform_refresh_sessions`
- `device.hardware_assets`
- `device.license_entitlements`
- `device.license_assignments`
- `device.hardware_bindings`
- `device.client_installations`
- `device.hardware_leases`
- `ops.sensitive_access_grants`
- `ops.authentication_attempts`

Assert every tenant-owned table has `tenant_id`, forced RLS, and a tenant policy. Assert platform tables have no tenant RLS and are granted only to the Platform database role. Assert no role is granted `BYPASSRLS`.

- [ ] **Step 2: Run tests and confirm missing migration failure**

Run: `./scripts/local-env.sh python -m pytest cloud/tests/test_migrations.py cloud/tests/test_postgres_tenant_context.py -q`

Expected: FAIL on missing schema objects.

- [ ] **Step 3: Implement migration 0003**

Use UUID primary keys, UTC `timestamptz`, immutable history rows, and explicit checks. Required constraints include:

```sql
CREATE UNIQUE INDEX uq_tenant_account_login
ON iam.tenant_accounts (login_name_hmac);

CREATE UNIQUE INDEX uq_open_hardware_binding
ON device.hardware_bindings (hardware_id)
WHERE unbound_at IS NULL;

CREATE UNIQUE INDEX uq_open_license_assignment
ON device.license_assignments (license_id)
WHERE unassigned_at IS NULL;

CREATE UNIQUE INDEX uq_open_hardware_lease
ON device.hardware_leases (hardware_id)
WHERE released_at IS NULL;
```

`license_entitlements.valid_until` must be later than `valid_from`. Binding/assignment rows close with `unbound_at`/`unassigned_at`; they are never deleted. `client_installations` has no unique ownership of a License. Seed `PLATFORM_*` roles idempotently.

- [ ] **Step 4: Add role-bound transaction tests**

With `TEST_POSTGRES_DSN*` unset, the test skips with a precise reason. When configured, verify:

1. tenant A cannot read tenant B;
2. changing tenant context within one transaction cannot leak rows;
3. the Platform pool cannot use a tenant query without the explicit target-tenant transaction helper;
4. the activation pool can consume an activation code but cannot read screening data;
5. no application role reports `rolbypassrls = true`.

- [ ] **Step 5: Run migration tests**

Run: `./scripts/local-env.sh python -m pytest cloud/tests/test_migrations.py cloud/tests/test_postgres_tenant_context.py -q`

Expected: PASS, with live tests skipped only when their documented DSNs are absent.

- [ ] **Step 6: Commit the schema**

```bash
git add cloud/migrations/0003_seed_mvp_access_control.sql cloud/tests/test_migrations.py cloud/tests/test_postgres_tenant_context.py
git commit -m "feat: add seed access control schema"
```

## Task 3: Implement password, token, and signed-License primitives

**Files:**

- Create: `cloud/access_control/__init__.py`
- Create: `cloud/access_control/passwords.py`
- Create: `cloud/api/access_auth.py`
- Test: `cloud/tests/test_access_auth.py`

- [ ] **Step 1: Write failing primitive tests**

Test that:

- password hashes use a random 16-byte salt and `scrypt` parameters encoded in the stored string;
- verification uses `hmac.compare_digest` and rejects malformed hashes;
- tenant access tokens expire after 15 minutes and include `typ=tenant_access`, `aud=feetforceplate-api`;
- Platform tokens use `typ=platform_access`, `aud=feetforceplate-platform`, and cannot verify with the tenant issuer;
- refresh tokens expose 32 random bytes once and persist only a keyed SHA-256 digest;
- Ed25519 License verification fails after any field mutation;
- `FFP-2026-TEST-0001` is rejected before repository lookup.

- [ ] **Step 2: Run the tests and confirm failure**

Run: `./scripts/local-env.sh python -m pytest cloud/tests/test_access_auth.py -q`

Expected: FAIL because the primitives do not exist.

- [ ] **Step 3: Implement password hashing**

Expose:

Expose `hash_password(password: str, *, salt: bytes | None = None) -> str` and
`verify_password(password: str, encoded: str) -> bool` as the only public
password primitive functions.

Use `hashlib.scrypt(n=2**15, r=8, p=1, dklen=32)` and a versioned `$ffp-scrypt$...` encoding. Enforce a 12-character minimum at the contract/service boundary.

- [ ] **Step 4: Implement separate issuers**

Add `TenantAccessContext`, `PlatformAccessContext`, `TenantAccessTokenIssuer`, `PlatformAccessTokenIssuer`, `RefreshTokenFactory`, and `LicenseDocumentSigner`. Do not reuse `TerminalTokenIssuer` or `OperationsTokenIssuer`. Include `token_version` so remote session revocation can invalidate access at refresh time.

- [ ] **Step 5: Run primitive tests**

Run: `./scripts/local-env.sh python -m pytest cloud/tests/test_access_auth.py -q`

Expected: PASS.

- [ ] **Step 6: Commit the authentication primitives**

```bash
git add cloud/access_control cloud/api/access_auth.py cloud/tests/test_access_auth.py
git commit -m "feat: add tenant and platform auth primitives"
```

## Task 4: Build the repository protocol and deterministic in-memory adapter

**Files:**

- Create: `cloud/access_control/repository.py`
- Test: `cloud/tests/test_access_repository.py`

- [ ] **Step 1: Write repository lifecycle tests**

Test one institution growing from one License/hardware/account group to three, then reducing to two. Verify no subject/session/report rows move, all resources keep the same tenant ID, and closed assignment/binding rows remain queryable. Test activation-code row locking semantics with an asyncio barrier: exactly one consumer succeeds.

- [ ] **Step 2: Run tests and confirm failure**

Run: `./scripts/local-env.sh python -m pytest cloud/tests/test_access_repository.py -q`

Expected: FAIL because the repository does not exist.

- [ ] **Step 3: Define records and protocol methods**

Create frozen records for tenant account, activation code, entitlement, assignment, hardware, binding, installation, refresh session, lease, Platform identity, role binding, sensitive grant, and immutable audit event. The protocol must expose transaction-shaped methods rather than mutable dictionaries, including:

The central protocol operation is `activate_account_atomically`, with keyword
arguments `login_name_hmac`, `activation_code_hash`, `hardware_id`,
`password_hash`, `installation_id`, and `activated_at`, returning an immutable
`ActivatedAccess` record.

- [ ] **Step 4: Implement `InMemoryAccessRepository`**

Use an `asyncio.Lock` around atomic operations. Return immutable copies. Keep append-only binding and audit histories. Add deterministic list methods needed by Platform operations; never expose raw credential hashes in response records.

- [ ] **Step 5: Run lifecycle tests**

Run: `./scripts/local-env.sh python -m pytest cloud/tests/test_access_repository.py -q`

Expected: PASS.

- [ ] **Step 6: Commit the repository boundary**

```bash
git add cloud/access_control/repository.py cloud/tests/test_access_repository.py
git commit -m "feat: add access repository boundary"
```

## Task 5: Implement provider provisioning and dynamic License control

**Files:**

- Create: `cloud/access_control/platform_service.py`
- Test: `cloud/tests/test_platform_provisioning.py`

- [ ] **Step 1: Write failing provisioning tests**

Cover:

1. `PLATFORM_OPERATIONS` can atomically create tenant + pending account + hardware + 6/12-month License + one-time activation code;
2. the response contains the raw activation code exactly once, while storage contains only its hash;
3. duplicate normalized account or hardware serial is rejected without partial rows;
4. renew accepts a new explicit `valid_until` and increments License version;
5. suspend/restore/revoke append immutable audit events and increment version;
6. reducing 3 -> 2 closes one assignment/binding but leaves the tenant database intact;
7. SUPPORT and ENGINEER cannot provision or alter License state.

- [ ] **Step 2: Run and confirm failure**

Run: `./scripts/local-env.sh python -m pytest cloud/tests/test_platform_provisioning.py -q`

Expected: FAIL because `PlatformProvisioningService` does not exist.

- [ ] **Step 3: Implement role policy and provisioning service**

Use an explicit permission matrix in code. Normalize login names with Unicode NFKC + lowercase + trimmed whitespace and compute lookup HMAC. Generate activation codes with `secrets.token_urlsafe(24)`. Return a signed License only after activation, never during pending provisioning.

- [ ] **Step 4: Run provisioning tests**

Run: `./scripts/local-env.sh python -m pytest cloud/tests/test_platform_provisioning.py -q`

Expected: PASS.

- [ ] **Step 5: Commit provisioning**

```bash
git add cloud/access_control/platform_service.py cloud/tests/test_platform_provisioning.py
git commit -m "feat: add provider provisioning and license control"
```

## Task 6: Implement atomic activation, login, refresh rotation, and rate limiting

**Files:**

- Create: `cloud/access_control/tenant_service.py`
- Modify: `cloud/access_control/repository.py`
- Test: `cloud/tests/test_tenant_authentication.py`

- [ ] **Step 1: Write failing activation and login tests**

Cover the full transaction:

- correct account + one-time code + exact hardware -> password saved, account/License activated, code consumed, installation recorded, signed License and token pair returned;
- wrong hardware/password confirmation/expired code -> no password saved and code remains unconsumed;
- replay of a consumed code is rejected;
- active account login works from a new installation without changing the License hardware binding;
- suspended/revoked/expired License permits login/report/upload claims but sets `allow_new_test=false`;
- rotating refresh invalidates the prior refresh token;
- refresh expires after 30 idle days or 180 absolute days;
- five failed attempts in 15 minutes lock that normalized account for 15 minutes without revealing whether it exists.

- [ ] **Step 2: Run and confirm failure**

Run: `./scripts/local-env.sh python -m pytest cloud/tests/test_tenant_authentication.py -q`

Expected: FAIL because the service does not exist.

- [ ] **Step 3: Implement `TenantAuthenticationService`**

Return one generic public rejection for invalid account/password/code/hardware. Accept an injected clock, password verifier, code-HMAC key, login-HMAC key, token issuer, refresh factory, and License signer for deterministic tests. Derive effective expiry at request time even if the stored state is still ACTIVE.

- [ ] **Step 4: Add remote session invalidation**

Account suspension increments `token_version` and revokes refresh sessions. License suspension does not destroy report/upload access; the refreshed access context carries separate claims for `allow_new_test`, `allow_upload`, and `allow_report_view`.

- [ ] **Step 5: Run authentication tests**

Run: `./scripts/local-env.sh python -m pytest cloud/tests/test_tenant_authentication.py -q`

Expected: PASS.

- [ ] **Step 6: Commit authentication service**

```bash
git add cloud/access_control/tenant_service.py cloud/access_control/repository.py cloud/tests/test_tenant_authentication.py
git commit -m "feat: add account activation and rotating sessions"
```

## Task 7: Implement online hardware lease semantics and the offline evidence boundary

**Files:**

- Create: `cloud/access_control/lease_service.py`
- Test: `cloud/tests/test_hardware_leases.py`
- Modify: `docs/superpowers/specs/2026-08-01-seed-mvp-license-access-design.md`

- [ ] **Step 1: Write failing lease tests**

Test acquire, renew, release, takeover after expiry, rejection by a second installation before expiry, and rejection when the authenticated License/hardware pair differs. Test that lease denial blocks only `allow_new_test`; it does not revoke upload/report claims.

- [ ] **Step 2: Run and confirm failure**

Run: `./scripts/local-env.sh python -m pytest cloud/tests/test_hardware_leases.py -q`

Expected: FAIL because the lease service does not exist.

- [ ] **Step 3: Implement `HardwareLeaseService`**

Use a 10-minute TTL, injected clock, and repository row lock. Renewal is idempotent for the same `installation_id`; another installation may acquire only after the old lease expires or is explicitly released.

- [ ] **Step 4: Amend the approved spec with the precise offline limitation**

Add this normative statement to the License/lease section:

> 在线时，以 10 分钟可续租硬件租约防止同一硬件被多个安装实例同时开始检测；离线 24 小时窗口内，以最后签名 License、实体硬件和本机可信时间为准。由于服务器不可见离线客户端，MVP 不声称能够证明多台离线电脑绝不并发。

- [ ] **Step 5: Run lease tests**

Run: `./scripts/local-env.sh python -m pytest cloud/tests/test_hardware_leases.py -q`

Expected: PASS.

- [ ] **Step 6: Commit lease semantics and spec clarification**

```bash
git add cloud/access_control/lease_service.py cloud/tests/test_hardware_leases.py docs/superpowers/specs/2026-08-01-seed-mvp-license-access-design.md
git commit -m "feat: enforce online hardware leases"
```

## Task 8: Add Platform IAM and time-boxed sensitive access

**Files:**

- Create: `cloud/access_control/platform_iam.py`
- Test: `cloud/tests/test_platform_iam.py`
- Modify: `cloud/access_control/repository.py`

- [ ] **Step 1: Write failing IAM tests**

Verify multiple Platform identities, independent role bindings, masked cross-tenant support views, and the role matrix. Raw patient identity access must require:

- explicit target tenant;
- a non-empty purpose code;
- a non-empty ticket/reference;
- OWNER or SUPPORT role;
- a fresh grant with a maximum 15-minute lifetime;
- an immutable issue/use/expiry audit chain.

ENGINEER sees operational metadata only; OPERATIONS manages tenants/Licenses but cannot reveal patient identity.

- [ ] **Step 2: Run and confirm failure**

Run: `./scripts/local-env.sh python -m pytest cloud/tests/test_platform_iam.py -q`

Expected: FAIL because Platform IAM is not implemented.

- [ ] **Step 3: Implement `PlatformIdentityService` and `SensitiveAccessService`**

Bootstrap the first OWNER only through a one-shot CLI/API composition hook, never a public endpoint. Hash Platform passwords with the same primitive but use separate refresh-session storage and token issuer. Mask names/contact by default before leaving the tenant transaction.

- [ ] **Step 4: Run IAM tests**

Run: `./scripts/local-env.sh python -m pytest cloud/tests/test_platform_iam.py -q`

Expected: PASS.

- [ ] **Step 5: Commit Platform IAM**

```bash
git add cloud/access_control/platform_iam.py cloud/access_control/repository.py cloud/tests/test_platform_iam.py
git commit -m "feat: add platform IAM and sensitive grants"
```

## Task 9: Expose separate tenant and Platform API surfaces

**Files:**

- Modify: `cloud/api/app.py`
- Modify: `cloud/api/errors.py`
- Test: `cloud/tests/test_access_api.py`
- Test: `cloud/tests/test_platform_api.py`

- [ ] **Step 1: Write failing route tests**

Add ASGI tests for:

```text
POST /v1/access/activate
POST /v1/access/login
POST /v1/access/refresh
POST /v1/access/logout
GET  /v1/access/license
POST /v1/access/hardware-lease
PUT  /v1/access/hardware-lease/{lease_id}
DELETE /v1/access/hardware-lease/{lease_id}

POST /v1/platform/login
POST /v1/platform/tenants
POST /v1/platform/tenants/{tenant_id}/licenses
PATCH /v1/platform/licenses/{license_id}
GET  /v1/platform/tenants
GET  /v1/platform/tenants/{tenant_id}/reports
POST /v1/platform/sensitive-access-grants
GET  /v1/platform/tenants/{tenant_id}/subjects/{subject_id}/identity
```

Verify wrong-audience tokens are 401, cross-tenant IDs in paths are 403, public failures do not reveal account existence, and error allowlists never emit secrets.

- [ ] **Step 2: Run and confirm route failure**

Run: `./scripts/local-env.sh python -m pytest cloud/tests/test_access_api.py cloud/tests/test_platform_api.py -q`

Expected: FAIL with missing routes/container services.

- [ ] **Step 3: Extend `ServiceContainer`**

Add optional `tenant_access`, `tenant_tokens`, `platform_access`, and `platform_tokens` fields. Register each route group only when its service and matching issuer are present. Keep legacy terminal/operations routes behind their existing optional services.

- [ ] **Step 4: Add dependencies and safe errors**

Create separate `tenant_context()` and `platform_context()` dependencies. Do not add a combined “either token” dependency. Add generic `AccessRejected`, `LicenseOperationDenied`, `HardwareLeaseConflict`, and `SensitiveAccessDenied` errors with a strict safe-details allowlist.

- [ ] **Step 5: Run route and legacy regression tests**

Run: `./scripts/local-env.sh python -m pytest cloud/tests/test_access_api.py cloud/tests/test_platform_api.py cloud/tests/test_api_contract.py cloud/tests/test_device_management_api.py cloud/tests/test_operations_api.py -q`

Expected: PASS; legacy tests continue to pass only in compositions that inject legacy services.

- [ ] **Step 6: Commit API surfaces**

```bash
git add cloud/api/app.py cloud/api/errors.py cloud/tests/test_access_api.py cloud/tests/test_platform_api.py
git commit -m "feat: expose tenant and platform access APIs"
```

## Task 10: Make seed access authoritative for ingestion without deleting legacy compatibility

**Files:**

- Modify: `cloud/api/app.py`
- Modify: `cloud/ingestion/service.py`
- Modify: `cloud/api/repository.py`
- Modify: `cloud/api/postgres.py`
- Test: `cloud/tests/test_tenant_access_ingestion.py`
- Test: `cloud/tests/test_api_tenant_isolation.py`

- [ ] **Step 1: Write failing tenant-token ingestion tests**

Verify a tenant access token can create subjects/consent/sessions/upload segments only inside its tenant. Verify `allow_upload=true` continues after License suspension, while `allow_new_test=false` blocks creation of a new session. An already-created session must still accept remaining segments and final manifest.

- [ ] **Step 2: Run and confirm failure**

Run: `./scripts/local-env.sh python -m pytest cloud/tests/test_tenant_access_ingestion.py cloud/tests/test_api_tenant_isolation.py -q`

Expected: FAIL because ingestion accepts only `TerminalContext`.

- [ ] **Step 3: Introduce a narrow ingestion principal protocol**

Add an immutable principal carrying `tenant_id`, `installation_id`, `hardware_id`, `allow_new_test`, and `allow_upload`. Adapt both `TenantAccessContext` and legacy `TerminalContext` at the API edge; do not let ingestion inspect token types.

- [ ] **Step 4: Separate start from finish authorization**

Check `allow_new_test` only on subject/consent/session-start operations that initiate new work. Check `allow_upload` on segment/manifest/status operations. Preserve all existing tenant RLS and idempotency behavior.

- [ ] **Step 5: Run focused and complete cloud tests**

Run: `./scripts/local-env.sh python -m pytest cloud/tests/test_tenant_access_ingestion.py cloud/tests/test_api_tenant_isolation.py -q`

Run: `./scripts/local-env.sh python -m pytest cloud/tests -q`

Expected: PASS.

- [ ] **Step 6: Commit authoritative ingestion access**

```bash
git add cloud/api/app.py cloud/ingestion/service.py cloud/api/repository.py cloud/api/postgres.py cloud/tests/test_tenant_access_ingestion.py cloud/tests/test_api_tenant_isolation.py
git commit -m "feat: authorize ingestion with tenant license context"
```

## Cloud Plan Completion Gate

- [ ] `./scripts/local-env.sh python -m pytest cloud/tests -q` passes.
- [ ] `./scripts/local-env.sh python -m mypy shared/contracts` passes.
- [ ] `./scripts/local-env.sh python -m ruff check shared cloud` passes.
- [ ] No production code recognizes `FFP-2026-TEST-0001`.
- [ ] Tests demonstrate one tenant expanding 1 -> 3 and contracting 3 -> 2 without data migration.
- [ ] Tests demonstrate tenant/Platform token audience separation and tenant A/B isolation.
- [ ] Evidence states that online lease exclusivity is proven and offline global exclusivity is not proven.
