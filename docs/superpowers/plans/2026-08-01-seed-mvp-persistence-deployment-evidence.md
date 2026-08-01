# Seed MVP Persistence, Aliyun Deployment, and Evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the account/License implementation into a persistent, recoverable seed-pilot service on `aliyun-agentic`, verify it through public port 7443 without overstating production readiness, and attach reproducible evidence to the authoritative Linear issues.

**Architecture:** Compose the new access-control services with PostgreSQL and an immutable private filesystem object store behind Nginx TLS. Separate migration, activation, tenant application, and Platform database roles. Use systemd for process supervision, least-privilege directories, daily encrypted backups, and a restore exercise. The current IP:7443 endpoint remains a controlled seed/integration endpoint; formal commercial ingress requires a domain, CA-issued certificate, and port 443.

**Tech Stack:** Python/uv wrapper, FastAPI/Uvicorn, PostgreSQL 16, asyncpg, Nginx, systemd, POSIX filesystem, pytest/httpx, SSH to `aliyun-agentic`, Linear.

## Global Constraints

- Run repository Python through `./scripts/local-env.sh`. Deployment must use the same wrapper/environment convention outside the OneDrive checkout.
- Never expose PostgreSQL 5432 publicly. Verify from the public internet that only the user-authorized API ingress is reachable.
- Seed service runs as a dedicated unprivileged user and receives only `0600` environment/secrets files plus `0700` data/backup directories.
- Database pools/roles are distinct: migration, activation, tenant application, Platform operations. No application role has `SUPERUSER` or `BYPASSRLS`.
- The object-store root is outside the code checkout. Writes use verified digest + atomic rename + immutable final keys. Do not serve it through Nginx.
- Health endpoints reveal only liveness/readiness and named dependency classes, never DSNs, paths, secrets, tenant counts, account names, hardware IDs, or stack traces.
- The public 7443 seed endpoint must use TLS, request/body limits, connection timeouts, rate limiting, generic auth errors, and structured redacted logs. An open port is not treated as authorization.
- A self-signed or private-CA IP certificate is acceptable only for controlled seed integration with explicit client trust/pinning. Do not label it production TLS. Formal customer rollout requires a domain + public CA certificate + 443.
- Backups are not “verified” until a clean restore instance passes schema, tenant-isolation, License-state, object-digest, and representative report checks.
- Never mark Linear Done solely from unit tests or replay. Each issue comment must distinguish local simulation, PostgreSQL integration, public network integration, physical hardware, operator, and formal production gates.
- Before every commit, inspect the dirty worktree and stage only files listed in the current task.
- Begin this plan only after the cloud plan completion gate. Run Task 7 after the client plan has completed through its packaged-composition and License-policy tasks.

---

## Task 1: Implement a persistent private filesystem object-store adapter

**Files:**

- Modify: `cloud/ingestion/object_store.py`
- Create: `cloud/tests/test_filesystem_object_store.py`

- [ ] **Step 1: Write failing adapter tests**

Test tenant-prefixed segment/manifest keys, digest and size rejection, idempotent same-content replay, conflict on different bytes at an immutable key, atomic cleanup of staging files after failure, path-traversal rejection, `0700` directories, and `0600` final files.

- [ ] **Step 2: Run and confirm failure**

Run: `./scripts/local-env.sh python -m pytest cloud/tests/test_filesystem_object_store.py -q`

Expected: FAIL because `FileSystemObjectStore` does not exist.

- [ ] **Step 3: Implement `FileSystemObjectStore`**

Resolve object keys below a configured root and assert `resolved_path.is_relative_to(root.resolve())`. Stream to a random file under `<root>/.staging`, compute size/digest, `fsync`, then atomically publish with `os.replace` only if the final key does not exist. If it exists, compare the verified digest and keep the immutable object.

- [ ] **Step 4: Run adapter and existing object-store tests**

Run: `./scripts/local-env.sh python -m pytest cloud/tests/test_filesystem_object_store.py cloud/tests/test_object_store.py -q`

Expected: PASS.

- [ ] **Step 5: Commit persistent object storage**

```bash
git add cloud/ingestion/object_store.py cloud/tests/test_filesystem_object_store.py
git commit -m "feat: add private filesystem object storage"
```

## Task 2: Implement the PostgreSQL access repository

**Files:**

- Create: `cloud/access_control/postgres.py`
- Create: `cloud/tests/test_postgres_access_repository.py`
- Modify: `cloud/api/postgres.py`

- [ ] **Step 1: Write repository parity tests**

Run the same behavioral fixtures against `InMemoryAccessRepository` and `PostgresAccessRepository`: provision, atomic activation, failed activation rollback, login lookup, refresh rotation, License suspend/restore/renew/revoke, lease conflict/takeover, 1 -> 3 -> 2 history, Platform roles, and sensitive access grants.

- [ ] **Step 2: Run and confirm the PostgreSQL adapter is missing**

Run: `./scripts/local-env.sh python -m pytest cloud/tests/test_postgres_access_repository.py -q`

Expected: FAIL on missing adapter, or explicit skip only when the test PostgreSQL DSNs are absent.

- [ ] **Step 3: Implement pool-separated repository methods**

Constructor signature:

`PostgresAccessRepository` receives three keyword-only pools named
`tenant_pool`, `activation_pool`, and `platform_pool`; it never falls back from
one pool to another.

Use row-locking `SELECT ... FOR UPDATE` statements for activation codes, License changes, refresh rotation, and hardware leases. Use `tenant_transaction()` for all tenant reads/writes. Platform operations choose a target tenant explicitly and use a helper that sets the same transaction-local tenant context; they never query tenant tables with an unrestricted connection.

- [ ] **Step 4: Run live repository parity tests**

Run after exporting the three test DSNs: `./scripts/local-env.sh python -m pytest cloud/tests/test_postgres_access_repository.py cloud/tests/test_postgres_tenant_context.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the PostgreSQL adapter**

```bash
git add cloud/access_control/postgres.py cloud/tests/test_postgres_access_repository.py cloud/api/postgres.py
git commit -m "feat: persist seed access control in postgres"
```

## Task 3: Add a persistent seed service composition and safe bootstrap CLI

**Files:**

- Create: `cloud/api/seed.py`
- Create: `cloud/api/run-seed.sh`
- Create: `cloud/access_control/cli.py`
- Create: `cloud/tests/test_seed_composition.py`
- Modify: `cloud/api/README.md`

- [ ] **Step 1: Write failing composition tests**

Test settings reject missing/short secrets, non-PostgreSQL DSNs, object roots inside the repository, HTTP public base URLs, shared tenant/Platform secrets, and a writable secret file broader than `0600`. Test readiness fails closed when PostgreSQL or object storage is unavailable.

- [ ] **Step 2: Run and confirm failure**

Run: `./scripts/local-env.sh python -m pytest cloud/tests/test_seed_composition.py -q`

Expected: FAIL because `SeedSettings`/`build_seed_app` do not exist.

- [ ] **Step 3: Implement `SeedSettings` and `build_seed_app`**

Load four DSNs, separate tenant/Platform token keys, License signing key, lookup/activation/refresh HMAC keys, object root, public base URL, and trusted proxy list from environment. Construct PostgreSQL repositories, `FileSystemObjectStore`, access services, ingestion service, and `ServiceContainer`. Do not inject legacy `devices`, legacy `operations`, or legacy terminal/operations token issuers.

- [ ] **Step 4: Implement safe CLI commands**

Expose:

```text
./scripts/local-env.sh python -m cloud.access_control.cli bootstrap-platform-owner
./scripts/local-env.sh python -m cloud.access_control.cli provision-tenant
./scripts/local-env.sh python -m cloud.access_control.cli rotate-platform-role
./scripts/local-env.sh python -m cloud.access_control.cli inspect-license --license-id "$FEETFORCEPLATE_LICENSE_ID"
```

Read secrets from `getpass`/stdin, print a newly generated one-time activation code once, and never print hashes/DSNs/private keys. `provision-tenant` requires an explicit confirmation summary but is non-interactive under `--json-input` for test automation.

- [ ] **Step 5: Run composition tests**

Run: `./scripts/local-env.sh python -m pytest cloud/tests/test_seed_composition.py -q`

Expected: PASS.

- [ ] **Step 6: Commit seed composition**

```bash
git add cloud/api/seed.py cloud/api/run-seed.sh cloud/access_control/cli.py cloud/tests/test_seed_composition.py cloud/api/README.md
git commit -m "feat: compose persistent seed access service"
```

## Task 4: Create deterministic ten-institution acceptance evidence locally

**Files:**

- Create: `scripts/verify_seed_access.py`
- Create: `cloud/tests/test_seed_access_end_to_end.py`
- Create: `docs/evidence/linear/RAY-116/README.md`
- Create: `docs/evidence/linear/RAY-116/seed-access-summary.json`

- [ ] **Step 1: Write the end-to-end acceptance test**

Provision ten tenants with one account/License/hardware each, activate all ten, upload one synthetic report/session per tenant, and assert every tenant sees exactly its own report. Then expand tenant 1 to three License/hardware/account groups and reduce it to two; verify all three historical data contributors remain in the same tenant data boundary.

- [ ] **Step 2: Add negative security cases**

Attempt cross-tenant report access, wrong-audience tokens, wrong hardware activation, activation replay, concurrent lease acquisition, expired/suspended/revoked new-test start, refresh replay, raw sensitive identity without grant, and use of `FFP-2026-TEST-0001` against cloud activation.

- [ ] **Step 3: Run against local in-memory composition**

Run: `./scripts/local-env.sh python -m pytest cloud/tests/test_seed_access_end_to_end.py -q`

Expected: PASS.

- [ ] **Step 4: Run against local PostgreSQL composition**

Run after exporting `FEETFORCEPLATE_SEED_CA_FILE`: `./scripts/local-env.sh python scripts/verify_seed_access.py --base-url https://127.0.0.1:7443 --ca-file "$FEETFORCEPLATE_SEED_CA_FILE" --output docs/evidence/linear/RAY-116/seed-access-summary.json`

Expected: JSON with ten isolated tenants, 1 -> 3 -> 2 history, negative-case results, server build SHA, certificate fingerprint, and no raw secrets/identity.

- [ ] **Step 5: Write the evidence scope**

The README must label synthetic users/reports as software/network evidence only. It must explicitly leave physical hardware identity, operator workflow, formal public TLS/domain, and clinical readiness open.

- [ ] **Step 6: Commit local acceptance tooling/evidence**

```bash
git add scripts/verify_seed_access.py cloud/tests/test_seed_access_end_to_end.py docs/evidence/linear/RAY-116
git commit -m "test: verify ten-tenant seed access lifecycle"
```

## Task 5: Add reviewed Aliyun deployment assets

**Files:**

- Create: `deploy/aliyun/seed/README.md`
- Create: `deploy/aliyun/seed/feetforceplate-seed.service`
- Create: `deploy/aliyun/seed/nginx-feetforceplate-seed.conf`
- Create: `deploy/aliyun/seed/postgresql-role-grants.sql`
- Create: `deploy/aliyun/seed/install-layout.sh`
- Create: `deploy/aliyun/seed/check-secrets.sh`
- Create: `cloud/tests/test_deployment_assets.py`

- [ ] **Step 1: Write failing deployment-asset tests**

Parse the service/Nginx/scripts and assert:

- dedicated user, `NoNewPrivileges=true`, `PrivateTmp=true`, `ProtectSystem=strict`, explicit writable paths, restart policy, and environment file path;
- Nginx listens on 7443 TLS, has TLS 1.2/1.3, body/header/time limits, `limit_req`, request ID forwarding, and no static mapping to object/backup roots;
- PostgreSQL binds localhost/private socket only;
- install script refuses root-owned application files and world/group-readable secret files;
- secrets checker prints names/permissions only, never values.

- [ ] **Step 2: Run and confirm asset failure**

Run: `./scripts/local-env.sh python -m pytest cloud/tests/test_deployment_assets.py -q`

Expected: FAIL because deployment assets do not exist.

- [ ] **Step 3: Implement systemd and filesystem layout**

Use `/opt/feetforceplate/app` for a read-only release, `/etc/feetforceplate/seed.env` for `0600` secrets, `/var/lib/feetforceplate/objects` for `0700` objects, and `/var/lib/feetforceplate/backups` for `0700` backups. Start `cloud.api.seed:app` on loopback port 8743; expose only Nginx 7443.

- [ ] **Step 4: Implement Nginx seed ingress controls**

Use a per-IP request zone plus a stricter login/activation zone, `client_max_body_size` consistent with segment limits, bounded keepalive/proxy timeouts, generic 429, and access logs that exclude request bodies and Authorization headers. Health endpoints may be rate-limited but unauthenticated.

- [ ] **Step 5: Run asset tests**

Run: `./scripts/local-env.sh python -m pytest cloud/tests/test_deployment_assets.py -q`

Expected: PASS.

- [ ] **Step 6: Commit deployment assets**

```bash
git add deploy/aliyun/seed cloud/tests/test_deployment_assets.py
git commit -m "ops: add hardened aliyun seed deployment"
```

## Task 6: Add backup, retention, and restore verification

**Files:**

- Create: `deploy/aliyun/seed/backup.sh`
- Create: `deploy/aliyun/seed/restore-verify.sh`
- Create: `deploy/aliyun/seed/feetforceplate-backup.service`
- Create: `deploy/aliyun/seed/feetforceplate-backup.timer`
- Create: `cloud/tests/test_backup_assets.py`
- Create: `docs/evidence/linear/RAY-97/restore-exercise.md`

- [ ] **Step 1: Write failing backup asset tests**

Assert `pg_dump --format=custom`, object manifest with SHA-256, encryption recipient configured outside the script, atomic finalization, daily timer, retention that never deletes the newest verified backup, and restore into a separate database/object root.

- [ ] **Step 2: Run and confirm failure**

Run: `./scripts/local-env.sh python -m pytest cloud/tests/test_backup_assets.py -q`

Expected: FAIL because backup assets do not exist.

- [ ] **Step 3: Implement backup and restore scripts**

The backup script takes a PostgreSQL snapshot plus an object inventory/digest manifest, encrypts the bundle with an environment-supplied public recipient, writes to a staging name, `fsync`s, and renames. It records build and schema versions without secrets. The restore script requires an empty target and refuses the live DSN/object root.

- [ ] **Step 4: Perform a clean restore exercise**

Restore into a temporary database and object root, then run `verify_seed_access.py --read-only-restore-check`. Verify tenant counts/isolation, active/suspended License states, ten representative object digests, and report metadata.

- [ ] **Step 5: Document exact evidence**

Record timestamp, backup ID, source/target schema versions, encrypted bundle digest, checks performed, pass/fail, and explicit exclusions. Do not record DSNs, paths containing secrets, accounts, or raw identifiers.

- [ ] **Step 6: Commit backup assets and restore evidence**

```bash
git add deploy/aliyun/seed/backup.sh deploy/aliyun/seed/restore-verify.sh deploy/aliyun/seed/feetforceplate-backup.service deploy/aliyun/seed/feetforceplate-backup.timer cloud/tests/test_backup_assets.py docs/evidence/linear/RAY-97/restore-exercise.md
git commit -m "ops: add and verify seed backup recovery"
```

## Task 7: Deploy to `aliyun-agentic` on the already-opened 7443 port

**Files:**

- Create: `docs/evidence/linear/RAY-116/aliyun-seed-deployment.md`
- Create: `docs/evidence/linear/RAY-116/aliyun-seed-summary.json`
- Modify: `docs/evidence/linear/RAY-100/aliyun-network-integration-20260731.md`

- [ ] **Step 1: Read-only preflight the server**

Run over the approved SSH target: inspect OS, memory/swap, disk, existing listeners, Nginx/PostgreSQL/systemd availability, current 7443 service, certificate fingerprint/expiry, firewall state, and application directory ownership. Do not stop or overwrite the current service during preflight.

- [ ] **Step 2: Request the user's help only for privileged prerequisites**

If native PostgreSQL/Nginx/systemd installation, service-user creation, firewall changes, or `/etc`/`/var/lib` layout requires sudo unavailable to the deployment account, provide the exact minimal commands and wait for the user. Do not fall back to a user crontab as the claimed final supervisor.

- [ ] **Step 3: Install a versioned release and migrate**

Upload a release archive identified by commit SHA, verify its SHA-256 on the server, install to `/opt/feetforceplate/releases/<sha>`, point `/opt/feetforceplate/app` at it, run migration 0003 with the migration role, and run the service under the application role. Preserve the prior release for rollback.

- [ ] **Step 4: Bootstrap Platform owner and one disposable acceptance tenant**

Use the safe CLI through an SSH TTY. Transfer the one-time activation code out-of-band for this controlled test; do not put it in shell history, logs, evidence files, or Linear.

- [ ] **Step 5: Run public 7443 acceptance**

From the local machine, use a pinned CA/fingerprint and run:

```bash
./scripts/local-env.sh python scripts/verify_seed_access.py \
  --base-url "$FEETFORCEPLATE_SEED_BASE_URL" \
  --ca-file "$FEETFORCEPLATE_SEED_CA_FILE" \
  --output docs/evidence/linear/RAY-116/aliyun-seed-summary.json
```

Verify health, activation, login, refresh rotation, License controls, lease conflict, tenant isolation, upload/report access after suspension, generic invalid-login responses, rate limits, and no secret leakage.

- [ ] **Step 6: Verify external exposure**

Confirm PostgreSQL 5432 and Uvicorn 8743 are unreachable externally; 7443 is reachable and TLS-only. Confirm an unauthenticated caller can learn only health status and cannot list tenants, Licenses, reports, hardware, or Platform identities.

- [ ] **Step 7: Verify restart and rollback**

Restart the service, prove persistent accounts/License/audit/object data remain, then exercise a non-destructive rollback dry run to the prior release without rolling back the database schema.

- [ ] **Step 8: Record bounded evidence**

The deployment evidence must say `seed pilot / integration`, not `production`. Keep domain + public CA + 443, real customer onboarding, physical hardware activation, and operator acceptance open.

- [ ] **Step 9: Commit deployment evidence**

```bash
git add docs/evidence/linear/RAY-116/aliyun-seed-deployment.md docs/evidence/linear/RAY-116/aliyun-seed-summary.json docs/evidence/linear/RAY-100/aliyun-network-integration-20260731.md
git commit -m "test: record aliyun seed access deployment"
```

## Task 8: Reconcile architecture, database, API, and module documentation

**Files:**

- Modify: `docs/产品需求文档_PRD.md`
- Modify: `docs/架构设计文档.md`
- Modify: `docs/数据库设计文档.md`
- Modify: `docs/通信接口设计文档.md`
- Modify: `docs/modules/05-sync-upload.md`
- Modify: `docs/modules/06-cloud-ingestion.md`
- Modify: `docs/modules/10-device-management.md`
- Modify: `docs/modules/11-observability-support.md`
- Modify: `cloud/api/README.md`
- Create: `cloud/tests/test_access_documentation.py`

- [ ] **Step 1: Write documentation consistency tests**

Assert authoritative docs contain `tenant account`, `license/2`, `hardware binding`, `client installation`, `PLATFORM_OWNER`, `PLATFORM_OPERATIONS`, `PLATFORM_SUPPORT`, `PLATFORM_ENGINEER`, `SensitiveAccessGrant`, 15-minute access token, 30-day idle/180-day refresh, 6/12-month License, and 24-hour offline grace.

Assert current sections no longer say License belongs to `terminal_id`, every institution has exactly one admin, customer searches/creates/joins tenants, Platform role has `BYPASSRLS`, or IP:7443 is production.

- [ ] **Step 2: Run and confirm documentation failure**

Run: `./scripts/local-env.sh python -m pytest cloud/tests/test_access_documentation.py -q`

Expected: FAIL on legacy wording.

- [ ] **Step 3: Update the authoritative documents**

Describe provider-provisioned seed onboarding, dynamic 1 -> 3 -> 2 License/device/account groups inside one tenant, multiple future institution admins without an MVP customer-admin backend, separate Platform IAM, private object-store adapter, additive PostgreSQL scaling path, and the online/offline lease limitation.

- [ ] **Step 4: Update API/module docs**

Document separate tenant/Platform token audiences and routes, legacy terminal compatibility status, upload/report availability after License suspension, health boundaries, backup/restore, and formal 443/domain gate.

- [ ] **Step 5: Run documentation tests**

Run: `./scripts/local-env.sh python -m pytest cloud/tests/test_access_documentation.py -q`

Expected: PASS.

- [ ] **Step 6: Commit documentation convergence**

```bash
git add docs/产品需求文档_PRD.md docs/架构设计文档.md docs/数据库设计文档.md docs/通信接口设计文档.md docs/modules/05-sync-upload.md docs/modules/06-cloud-ingestion.md docs/modules/10-device-management.md docs/modules/11-observability-support.md cloud/api/README.md cloud/tests/test_access_documentation.py
git commit -m "docs: align product and architecture with seed access model"
```

## Task 9: Produce issue-specific evidence and synchronize Linear

**Files:**

- Modify: `docs/evidence/linear/RAY-97/README.md`
- Modify: `docs/evidence/linear/RAY-98/README.md`
- Modify: `docs/evidence/linear/RAY-99/README.md`
- Modify: `docs/evidence/linear/RAY-100/README.md`
- Modify: `docs/evidence/linear/RAY-103/README.md`
- Modify: `docs/evidence/linear/RAY-116/README.md`
- Create: `docs/evidence/linear/RAY-98/platform-operations-summary.json`
- Create: `docs/evidence/linear/RAY-103/platform-iam-summary.json`

- [ ] **Step 1: Run the complete local regression**

Run: `./scripts/local-env.sh python -m pytest -q --junitxml=docs/evidence/linear/RAY-116/pytest-full-seed-access.xml`

Expected: PASS. Record test count, duration, commit SHA, and environment; do not infer physical/production completion from this result.

- [ ] **Step 2: Build the evidence matrix**

For every acceptance criterion in RAY-97, RAY-98, RAY-99, RAY-100, RAY-103, and RAY-116, link one concrete artifact/test. Mark each criterion `PROVEN_LOCAL`, `PROVEN_POSTGRES`, `PROVEN_ALIYUN_SEED`, `NEEDS_HARDWARE`, or `NEEDS_FORMAL_INGRESS`; do not use an unqualified “complete”.

- [ ] **Step 3: Refresh Linear issue snapshots**

Read the live issues immediately before editing. Confirm RAY-116 remains the integrated acceptance issue, RAY-97 the data plane, RAY-98 Platform operations, RAY-99 upload auth, RAY-100 client execution, RAY-96 packaging/activation, and RAY-103 Platform IAM. If any description has drifted, reconcile it to the approved spec before posting evidence.

- [ ] **Step 4: Post concise evidence comments**

Each comment includes commit SHA, exact test/evidence links, proven scope, remaining gates, and whether status should change. Never paste credentials, IP secrets, raw account names, activation codes, hardware serials, DSNs, or sensitive identity.

- [ ] **Step 5: Change status only when the issue's own acceptance is fully proven**

- RAY-97 may complete after persistent PostgreSQL/object storage, isolation, backup restore, and seed deployment evidence pass.
- RAY-98 may complete after provisioning, 1 -> 3 -> 2, remote License control, multiple Platform identities, and audit evidence pass.
- RAY-100 may complete after packaged activation/login/replacement-computer/offline/lock evidence pass; physical hardware-specific criteria remain open if no real device run exists.
- RAY-103 may complete after Platform IAM, masking, 15-minute grants, and audit evidence pass.
- RAY-116 completes only after all its non-deferred MVP criteria pass; formal domain/443 and offline global exclusivity remain explicitly deferred, not silently checked.

- [ ] **Step 6: Commit the evidence indexes**

```bash
git add docs/evidence/linear/RAY-97 docs/evidence/linear/RAY-98 docs/evidence/linear/RAY-99 docs/evidence/linear/RAY-100 docs/evidence/linear/RAY-103 docs/evidence/linear/RAY-116
git commit -m "docs: index seed access evidence for Linear"
```

## Deployment and Evidence Completion Gate

- [ ] PostgreSQL repository parity and live RLS/role tests pass.
- [ ] Filesystem object store is private, atomic, digest-verified, and outside the checkout.
- [ ] A clean encrypted-backup restore exercise passes.
- [ ] Aliyun 7443 seed endpoint passes activation/login/refresh/License/lease/isolation/upload negative cases with pinned TLS trust.
- [ ] External probes show 5432 and loopback Uvicorn are not public.
- [ ] systemd restart preserves database/object/audit state.
- [ ] Documentation contains no current terminal-bound License or customer tenant-search/admin contradictions.
- [ ] Linear evidence comments distinguish local, PostgreSQL, Aliyun seed, physical hardware, and formal production gates.
- [ ] Domain + public CA + 443 remains an explicit commercial rollout gate until separately proven.
