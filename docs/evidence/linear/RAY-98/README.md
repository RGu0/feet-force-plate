# RAY-98 Evidence — 机构、终端、设备与 License 运营后台

- Issue: `RAY-98`
- Title: 机构、终端、设备与 License 运营后台
- URL: https://linear.app/ray-app/issue/RAY-98/机构终端设备与-license-运营后台
- Linear snapshot: `2026-07-20T10:11:13Z`
- Evidence refreshed: `2026-07-20T10:22:13Z`
- Status at implementation start: `In Progress`
- Milestone: `P5：商业运营`
- Priority: `High`
- Relations: no declared blockers, blocked issues, related issues, duplicates, releases, or customer needs
- Baseline: `c0e4f38113453f2c517158347b499618ce19f6f6`
- RAY-100 prerequisite: `a4642125c887addf932dbf00acb67839dbc1a5fa`
- RAY-98 implementation commit: recorded by the evidence follow-up commit after the implementation commit is created

## Acceptance snapshot and result

- [~] Institution/site/terminal/device registration, binding, suspension/revocation, and append-only safe audit behavior are implemented through strict contracts, an operations API, and the deterministic reference repository. The P5 PostgreSQL schema is supplied but its production repository adapter/live deployment is not verified.
- [~] One-time activation credential issuance persists only an HMAC lookup value and can prebind a tenant/site/device; RAY-100 consumes it and issues terminal identity. Real credential rotation/certificate lifecycle and HSM/secret-manager integration remain external.
- [x] Ed25519 License/Feature Flag issue, renewal, revocation, canonical signing, and monotonically increasing version history are automatically verified.
- [x] Terminal health returns last online, app/config/protocol versions, pending sessions/bytes, latest device state, and counted stable error codes from accepted heartbeats, with no subject/report-link fields.
- [~] Staged rollout percentage, target/minimum/rollback versions, package digest/signature, and lifecycle states are versioned backend metadata. No client installer, package download, rollout executor, or real rollback is implemented here.
- [x] Operations identity claims carry tenant, site scope, and explicit permissions. Cross-tenant and out-of-scope access is denied and audited in API/service tests.
- [x] Support data access is separated into `RAW_DATA`, `IDENTITY`, `LOGS`, and `DIAGNOSTICS`, each mapped to a distinct permission and short-lived audited decision.
- [~] Authorization/audit decisions are implemented, but actual raw/identity/log object retrieval adapters and human approval workflows are intentionally absent.
- [x] Operations contracts reject unknown fields, the P5 schema has no public-report URL, and OpenAPI verification confirms no operations subject-public-report route.

`[x]` means repeatable automatic evidence exists. `[~]` means the contract/reference backend or migration exists but deployed persistence, external execution, or manual acceptance is missing.

## Implementation files and key decisions

- `shared/contracts/operations.py`, `shared/contracts/device_policy.py`, `shared/contracts/__init__.py`
  - Strict operations permissions, site/device/binding summaries, activation issuance, License lifecycle, terminal health, upgrade policy, and separated data-access decisions.
  - Adds signed `license_version` to the License document so a stale signed document cannot masquerade as the latest renewal/revocation version.
- `cloud/device_management/operations.py`, `cloud/device_management/__init__.py`
  - Permission-first operations service. Tenant/site comes only from `OperationsContext`; request bodies never select tenant.
  - Issues HMAC-indexed activation codes, signs License versions with Ed25519, composes heartbeat health/error trends, stores upgrade metadata, and emits allowed/denied audits.
- `cloud/api/operations_auth.py`
  - Separate terminal-independent operations token boundary containing actor, tenant, site scope, permissions, expiry, key ID, and constant-time HMAC verification. Production IAM/SSO must map claims to the same context; no token-minting route is exposed.
- `cloud/api/app.py`
  - Adds `/v1/operations/*` API routes for sites, devices, bindings, terminal status, activation codes, License lifecycle, health, upgrade policy, and data-access authorization.
- `cloud/api/repository.py`
  - Extends the deterministic reference repository with tenant/site/device operations, health derived from real accepted heartbeat contracts, versioned License state, upgrade metadata, and safe audits.
- `cloud/migrations/0002_p5_device_operations.sql`
  - Adds tenant-scoped IAM users/roles/site bindings, versioned signed licenses, upgrade policies, and categorized support grants.
  - Enables and forces RLS on every new tenant table with `ops.current_tenant_id()` `USING/WITH CHECK` policies.
- `cloud/api/README.md`
  - Documents migration order, separate operations identity, signing material, scope enforcement, and lack of public report links.
- `cloud/tests/test_operations_control_plane.py`, `test_operations_api.py`, `test_operations_migration.py`
  - Repeatable multi-tenant, scope, audit, License, health, upgrade, RLS, access-category, and OpenAPI evidence.
- `cloud/tests/test_device_management.py`
  - Makes token tamper verification deterministic by changing a real signature byte rather than an ambiguous Base64URL tail bit.

Key decisions:

- Operations and terminal credentials are distinct principals. An operations token cannot be treated as terminal identity, and no request body may override tenant scope.
- Activation code plaintext is returned only at issuance. The repository receives only a keyed HMAC value.
- License renew/revoke appends a newly signed version; prior signed facts remain immutable.
- Support access authorizes a category and purpose for a short window. It does not return raw, identity, log, or diagnostic content itself.
- Operations health is deliberately an operational summary. It carries no subject identity, raw pressure payload, report content, or public report URL.
- Upgrade policy metadata never authorizes installation during acquisition; execution and rollback are client responsibilities.

## Verification commands and results

Initial RED evidence:

```text
PYTHONPATH=. /private/tmp/feetforceplate-p3-venv/bin/python -m unittest cloud.tests.test_operations_control_plane cloud.tests.test_operations_migration -v
ModuleNotFoundError: No module named 'cloud.device_management.operations'
FileNotFoundError: cloud/migrations/0002_p5_device_operations.sql
Ran 4 tests; FAILED (errors=4)
```

Operations API RED evidence:

```text
PYTHONPATH=. /private/tmp/feetforceplate-p3-venv/bin/python -m unittest cloud.tests.test_operations_api -v
ModuleNotFoundError: No module named 'cloud.api.operations_auth'
Ran 1 test; FAILED (errors=1)
```

Targeted GREEN evidence:

```text
PYTHONPATH=. /private/tmp/feetforceplate-p3-venv/bin/python -m unittest cloud.tests.test_operations_control_plane cloud.tests.test_operations_migration -v
Ran 11 tests in 0.016s; OK

PYTHONPATH=. /private/tmp/feetforceplate-p3-venv/bin/python -m unittest cloud.tests.test_operations_api -v
Ran 3 tests in 0.106s; OK
```

Full regression evidence:

```text
PYTHONPATH=. /private/tmp/feetforceplate-p3-venv/bin/python -m unittest discover -s cloud/tests -v
Ran 79 tests in 0.219s; OK
```

Compilation and whitespace evidence:

```text
PYTHONPATH=. /private/tmp/feetforceplate-p3-venv/bin/python -m compileall -q cloud shared
exit 0

git diff --check
exit 0
```

## Automatic versus integration/manual verification boundary

Automatically verified here:

- site/device registration, binding, terminal status, and audit action sequence;
- tenant and site-scope denial at service and HTTP boundaries;
- one-time activation-code plaintext is not present in repository storage;
- License issue/renew/revoke produces valid signatures and versions 1/2/3;
- accepted heartbeats produce last-online/version/backlog/device/error-trend health summaries;
- upgrade policy rollout/rollback metadata state transitions;
- separate raw/identity/log/diagnostic permissions and allowed/denied audit outcomes;
- operations OpenAPI has no subject public-report route;
- P5 tables force tenant RLS and constrain License versions/access categories;
- all RAY-97/RAY-99/RAY-100 regressions, including deterministic token tamper rejection.

Not verified here:

- live PostgreSQL application of `0002`, RLS role matrix, connection-pool tenant isolation, concurrent control-plane writes, or a production asyncpg operations repository;
- real IAM/SSO authentication, group/role synchronization, MFA, account lifecycle, or claim revocation latency;
- private signing key in HSM/KMS, signing-key rotation, compromised-key recovery, or production License issuance policy;
- operations UI usability/accessibility and human support authorization workflow;
- actual raw/identity/log/diagnostic object retrieval and independent storage-role grants;
- upgrade package hosting/download, platform signature verification, staged rollout executor, client install/rollback, or manual recovery;
- real device identity rotation, hardware binding, online/offline fleet alerts, or alert deduplication/runbooks.

Because these live persistence, IAM, key-management, UI, hardware, support, and upgrade checks are missing, RAY-98 must not be marked `Done`; it is eligible only for `In Review`.

## Failures and limitations

- The operations API currently uses a deterministic reference repository. The P5 PostgreSQL schema is provided, but deployment must add and integration-test the production operations repository/transaction implementation before release.
- The bundled HMAC operations token is an integration boundary, not a production SSO issuer. Production must verify external IAM claims and instantiate `OperationsContext` without exposing token minting.
- The implementation provides authorization decisions and audits, not sensitive-data viewers or public report delivery.
- No secrets, personal data, activation-code plaintext, raw pressure frames, diagnostic contents, or customer report data are stored in this evidence directory.
