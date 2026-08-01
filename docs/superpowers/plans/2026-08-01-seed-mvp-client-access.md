# Seed MVP Client Access Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect the packaged desktop application to the seed License service so a pre-provisioned institution can activate once, log in on a replacement computer, enforce License/hardware policy, continue safe offline work, and optionally auto-lock without interrupting acquisition or background upload.

**Architecture:** Add a client access adapter and a small local access cache. Secrets live in the operating-system credential store; SQLite contains only non-secret authorization metadata and trusted timestamps. The UI asks for the provider-issued institution account and one-time activation code, discovers the physical hardware through the existing hardware runtime, and hands an authenticated session into the existing mandatory startup gate. A pure session-lock state machine is integrated at the Qt composition edge.

**Tech Stack:** Python 3.11, PySide6, httpx, keyring, SQLite, existing device policy contracts, pytest/pytest-qt.

## Global Constraints

- Run every Python/test command through `./scripts/local-env.sh`.
- The License follows the institution account and registered physical hardware, never the computer. `client_installation_id` is replaceable audit/session metadata.
- Production activation requires a stable `usb-serial-*` identity from `client.device.serial_transport.stable_hardware_identity`. If the hardware exposes no USB serial number, activation stops with a safe operator message; production code must not synthesize identity from port path, VID/PID, hostname, or MAC address.
- Preserve the documented local UI test License flow, but keep it process-memory-only and incapable of producing cloud tokens, signed Licenses, hardware leases, uploads, or production startup handoff.
- Store refresh tokens only in keyring. Never store access tokens, passwords, or activation codes in SQLite or logs.
- A signed License plus last trusted online timestamp may permit new tests for at most 24 hours offline, subject to the existing 50-session/2-GiB gates. Clock rollback blocks new tests.
- Online acquisition start requires the current hardware lease. During offline grace, global cross-computer exclusivity is unprovable; surface that as an evidence limitation, not an implementation success.
- Locking hides interactive content only. It does not stop an active acquisition, report finalization, token refresh, heartbeat, or upload worker.
- Lock options are Never, 5, 15, 30, or 60 minutes; default is 30 minutes. If the timeout occurs during acquisition/finalization, lock immediately after the protected operation ends.
- Begin contract/store/UI work only after cloud-plan Task 1 fixes the shared types. Begin live adapter/composition acceptance after cloud-plan Task 9 exposes the routes.

---

## Task 1: Add a production cloud-access client with safe errors

**Files:**

- Create: `client/cloud/__init__.py`
- Create: `client/cloud/access_client.py`
- Test: `client/tests/test_access_client.py`

- [ ] **Step 1: Write failing HTTP adapter tests**

Use `httpx.MockTransport` to verify exact calls to activate, login, refresh, logout, fetch License, acquire/renew/release lease. Assert 401/403/409 map to public client exceptions without copying server details or response bodies.

- [ ] **Step 2: Run and confirm failure**

Run: `./scripts/local-env.sh python -m pytest client/tests/test_access_client.py -q`

Expected: FAIL because `client.cloud.access_client` does not exist.

- [ ] **Step 3: Implement `CloudAccessClient`**

Expose synchronous methods suitable for the existing Qt composition, implemented over a configured `httpx.Client` with connect/read/write timeouts and TLS verification enabled:

`CloudAccessClient` exposes typed `activate`, `login`, `refresh`, `logout`,
`fetch_license`, `acquire_hardware_lease`, `renew_hardware_lease`, and
`release_hardware_lease` methods using the shared request/response contracts.

Send a UUID correlation ID on every request. Redact `Authorization`, password, activation code, and refresh token from exception text.

- [ ] **Step 4: Run adapter tests**

Run: `./scripts/local-env.sh python -m pytest client/tests/test_access_client.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the adapter**

```bash
git add client/cloud/__init__.py client/cloud/access_client.py client/tests/test_access_client.py
git commit -m "feat: add desktop access service client"
```

## Task 2: Persist non-secret access state and keyring refresh tokens

**Files:**

- Create: `client/cloud/access_store.py`
- Test: `client/tests/test_access_store.py`

- [ ] **Step 1: Write failing store tests**

Test that SQLite stores `tenant_id`, `account_id`, `license_id`, `hardware_id`, `client_installation_id`, signed License envelope, License version, last trusted server UTC/monotonic pair, and lock preference. Assert the database bytes do not contain password, activation code, access token, or refresh token. Use a fake keyring adapter to verify refresh-token set/get/delete.

- [ ] **Step 2: Run and confirm failure**

Run: `./scripts/local-env.sh python -m pytest client/tests/test_access_store.py -q`

Expected: FAIL because `ClientAccessStore` does not exist.

- [ ] **Step 3: Implement the access store**

Create a dedicated `access.sqlite3` under the existing platform data directory rather than changing the sensitive session spool schema. Use `PRAGMA journal_mode=WAL`, `synchronous=FULL`, foreign keys, atomic transactions, and `0600` best-effort file permissions. Define a narrow `CredentialStore` protocol and a production `KeyringCredentialStore(service_name="FeetForcePlate.access")`.

- [ ] **Step 4: Add clock-rollback detection**

Persist a server-signed/observed UTC value with local monotonic and wall-clock observations. Mark the clock untrusted if wall time moves backward beyond five minutes or the monotonic sequence restarts without a successful online refresh. A clock-untrusted state blocks new tests but never deletes cached reports or pending uploads.

- [ ] **Step 5: Run store tests**

Run: `./scripts/local-env.sh python -m pytest client/tests/test_access_store.py -q`

Expected: PASS.

- [ ] **Step 6: Commit local access persistence**

```bash
git add client/cloud/access_store.py client/tests/test_access_store.py
git commit -m "feat: persist non-secret client access state"
```

## Task 3: Update first-use activation UI to the provider-provisioned flow

**Files:**

- Modify: `client/app/institution_access.py`
- Modify: `client/tests/test_institution_access_ui.py`
- Create: `client/tests/test_seed_activation_ui.py`

- [ ] **Step 1: Write failing UI tests**

Assert the registration page contains:

- institution account;
- one-time activation code/License code;
- new password and confirmation;
- connected hardware status and opaque stable hardware ID suffix;
- Activate action.

Assert it does **not** ask for institution name, institution search, new institution creation, tenant selection, or customer administrator role.

- [ ] **Step 2: Run and confirm UI failure**

Run: `./scripts/local-env.sh python -m pytest client/tests/test_institution_access_ui.py client/tests/test_seed_activation_ui.py -q`

Expected: FAIL because the old page asks the customer to create/select organization details.

- [ ] **Step 3: Change the registration callback contract**

Replace `on_validate_license` + dictionary-based `on_register` with one typed activation callback receiving account, activation code, password, confirmation, and stable hardware ID. Keep login callback unchanged. Disable Activate while no stable physical hardware identity is present.

- [ ] **Step 4: Preserve the local test boundary**

Keep `LOCAL_UI_TEST_LICENSE` accepted only when `allow_local_test_handoff=True`. The local path may create an in-memory UI account for visual/testing purposes but must never call the production activation callback or write `ClientAccessStore`.

- [ ] **Step 5: Run UI tests**

Run: `./scripts/local-env.sh python -m pytest client/tests/test_institution_access_ui.py client/tests/test_seed_activation_ui.py -q`

Expected: PASS.

- [ ] **Step 6: Commit activation UI**

```bash
git add client/app/institution_access.py client/tests/test_institution_access_ui.py client/tests/test_seed_activation_ui.py
git commit -m "feat: align activation UI with provisioned accounts"
```

## Task 4: Discover and validate the bound physical hardware before activation

**Files:**

- Create: `client/cloud/hardware_identity.py`
- Modify: `client/hardware_standardization/runtime.py`
- Test: `client/tests/test_seed_hardware_identity.py`

- [ ] **Step 1: Write failing identity tests**

Test stable USB serial identity success and rejection when only port path, VID/PID, description, or hostname is available. Test multiple available supported devices returns an explicit selection-required result rather than silently binding the first one.

- [ ] **Step 2: Run and confirm failure**

Run: `./scripts/local-env.sh python -m pytest client/tests/test_seed_hardware_identity.py -q`

Expected: FAIL because activation-specific discovery does not exist and the runtime currently selects the first port.

- [ ] **Step 3: Add `ActivationHardwareIdentityProvider`**

Reuse `enumerate_ch340_ports` and `stable_hardware_identity`; do not duplicate serial heuristics. Return `NOT_FOUND`, `BUSY`, `IDENTITY_UNAVAILABLE`, `MULTIPLE_DEVICES`, or a stable opaque identity. Do not open the device for a full acquisition during the identity-only probe.

- [ ] **Step 4: Make runtime selection explicit**

Allow `HardwareRuntime.connect_startup(expected_hardware_identity=bound_identity)` and reject a connected supported device whose stable ID differs from the authenticated License. Keep the existing no-argument behavior only for replay/legacy tests.

- [ ] **Step 5: Run identity and hardware regressions**

Run: `./scripts/local-env.sh python -m pytest client/tests/test_seed_hardware_identity.py client/tests/test_serial_transport.py client/tests/test_hardware_standardization.py -q`

Expected: PASS.

- [ ] **Step 6: Commit hardware binding support**

```bash
git add client/cloud/hardware_identity.py client/hardware_standardization/runtime.py client/tests/test_seed_hardware_identity.py
git commit -m "feat: verify license-bound physical hardware"
```

## Task 5: Implement login, activation, refresh, and replacement-computer orchestration

**Files:**

- Create: `client/cloud/runtime.py`
- Modify: `client/app/packaged_entry.py`
- Modify: `client/tests/test_ray_101_packaged_composition.py`
- Create: `client/tests/test_seed_access_runtime.py`

- [ ] **Step 1: Write failing orchestration tests**

Cover:

1. activation writes only returned non-secret metadata and keyring refresh token;
2. login from a new `client_installation_id` succeeds while `hardware_id` and `license_id` remain unchanged;
3. access-token expiry triggers one refresh and refresh rotation;
4. invalid refresh clears only credentials, not reports/session spool;
5. a hardware mismatch stops before mandatory startup validation;
6. production `main()` injects the real access runtime when required settings exist;
7. no settings preserves a clear service-unavailable screen, not a silent local bypass.

- [ ] **Step 2: Run and confirm failure**

Run: `./scripts/local-env.sh python -m pytest client/tests/test_seed_access_runtime.py client/tests/test_ray_101_packaged_composition.py -q`

Expected: FAIL because the runtime and new session identifiers do not exist.

- [ ] **Step 3: Replace terminal ownership in the packaged session**

Use:

```python
@dataclass(frozen=True)
class AuthenticatedInstitutionSession:
    tenant_id: str
    account_id: str
    license_id: str
    hardware_id: str
    client_installation_id: str
    access_token: str
    signed_license: str
```

Do not retain `terminal_id` as a License attribute. If startup validation still needs an audit identity, pass `client_installation_id` through a renamed `audit_actor_id` parameter and keep database compatibility inside the audit adapter.

- [ ] **Step 4: Implement `ClientAccessRuntime`**

Coordinate `CloudAccessClient`, `ClientAccessStore`, keyring, hardware identity provider, and an injected clock. Build `InstitutionAuthenticationPort` and activation callback adapters for `InstitutionApplication`.

- [ ] **Step 5: Compose production settings**

Read `FEETFORCEPLATE_API_BASE_URL` and a CA bundle path from environment/settings. Require HTTPS and reject `verify=False`. Allow the current IP/self-signed 7443 endpoint only under explicit `FEETFORCEPLATE_INTEGRATION_MODE=1`; display “联调环境” in that mode and do not call it production.

- [ ] **Step 6: Run orchestration tests**

Run: `./scripts/local-env.sh python -m pytest client/tests/test_seed_access_runtime.py client/tests/test_ray_101_packaged_composition.py -q`

Expected: PASS.

- [ ] **Step 7: Commit packaged composition**

```bash
git add client/cloud/runtime.py client/app/packaged_entry.py client/tests/test_seed_access_runtime.py client/tests/test_ray_101_packaged_composition.py
git commit -m "feat: connect packaged app to seed access service"
```

## Task 6: Unify signed License, offline quota, and hardware lease policy

**Files:**

- Modify: `shared/contracts/device_policy.py`
- Create: `client/cloud/policy.py`
- Modify: `client/spool/state_store.py`
- Test: `client/tests/test_seed_license_policy.py`
- Modify: `cloud/tests/test_device_policy.py`

- [ ] **Step 1: Write failing policy matrix tests**

Parameterize ACTIVE/SUSPENDED/REVOKED/expired, online/offline, lease held/conflict, clock trusted/rollback, 24-hour boundary, 50-session boundary, and 2-GiB boundary. Every case asserts four independent capabilities: start new test, finalize current test, view report, upload.

- [ ] **Step 2: Run and confirm failure**

Run: `./scripts/local-env.sh python -m pytest client/tests/test_seed_license_policy.py cloud/tests/test_device_policy.py -q`

Expected: FAIL because policy still requires terminal-bound `license/1`.

- [ ] **Step 3: Add `license/2` verification and capability decision**

Verify Ed25519 signature, tenant/account/License/hardware match, validity, and monotonic License version. Reject downgrade/replay. Keep `license/1` verifier in a named legacy adapter only.

- [ ] **Step 4: Reuse existing spool limits**

Read `OfflineSnapshot` from `StateStore`; do not introduce a second quota source. Record successful trusted online contact only after a verified HTTPS response and signed License validation.

- [ ] **Step 5: Implement online/offline lease behavior**

When online, require an unexpired lease belonging to this installation. When the network is unreachable and last trusted contact is within 24 hours, allow from the signed License and local quotas; mark the decision evidence as `OFFLINE_GRACE_NO_GLOBAL_LEASE_PROOF`.

- [ ] **Step 6: Run policy tests**

Run: `./scripts/local-env.sh python -m pytest client/tests/test_seed_license_policy.py cloud/tests/test_device_policy.py -q`

Expected: PASS.

- [ ] **Step 7: Commit policy integration**

```bash
git add shared/contracts/device_policy.py client/cloud/policy.py client/spool/state_store.py client/tests/test_seed_license_policy.py cloud/tests/test_device_policy.py
git commit -m "feat: enforce account hardware license policy"
```

## Task 7: Add auto-lock as an independent UI privacy boundary

**Files:**

- Create: `client/app/session_lock.py`
- Modify: `client/app/qt_shell.py`
- Create: `client/tests/test_session_lock.py`
- Create: `client/tests/test_session_lock_qt.py`

- [ ] **Step 1: Write failing pure state-machine tests**

Test Never/5/15/30/60 options, 30-minute default, user activity reset, pending lock during acquisition/finalization, immediate lock after protected work ends, unlock with account password, and failed unlock rate limiting.

- [ ] **Step 2: Run and confirm failure**

Run: `./scripts/local-env.sh python -m pytest client/tests/test_session_lock.py -q`

Expected: FAIL because the state machine does not exist.

- [ ] **Step 3: Implement pure lock state**

Define `LockTimeout`, `SessionActivity`, `LockState`, and `SessionLockController` with an injected monotonic clock. The controller must not know Qt widgets or cloud clients.

- [ ] **Step 4: Write and implement Qt overlay tests**

Install an application event filter for keyboard/mouse/touch activity. Add a full-window lock overlay that masks patient/report content and requests reauthentication through the access runtime. Do not close or disable background worker objects.

- [ ] **Step 5: Run lock tests**

Run: `./scripts/local-env.sh python -m pytest client/tests/test_session_lock.py client/tests/test_session_lock_qt.py -q`

Expected: PASS.

- [ ] **Step 6: Commit session locking**

```bash
git add client/app/session_lock.py client/app/qt_shell.py client/tests/test_session_lock.py client/tests/test_session_lock_qt.py
git commit -m "feat: add configurable institution session lock"
```

## Task 8: Keep refresh, heartbeat, and uploads running independently of UI lock

**Files:**

- Modify: `client/cloud/runtime.py`
- Modify: `client/sync/worker.py`
- Create: `client/tests/test_background_access_continuity.py`

- [ ] **Step 1: Write failing background-continuity tests**

With the Qt session locked, prove queued upload continues, refresh rotates before expiry, and heartbeat records License/hardware/installation status without raw identifiers in logs. Prove License suspension stops a subsequent new-test decision while a current upload finishes.

- [ ] **Step 2: Run and confirm failure**

Run: `./scripts/local-env.sh python -m pytest client/tests/test_background_access_continuity.py -q`

Expected: FAIL because background workers do not receive the access runtime.

- [ ] **Step 3: Add a thread-safe token provider**

Workers request a current access token through a narrow provider that serializes refresh rotation. They do not read keyring or SQLite directly. A refresh failure moves work to retry/backoff without deleting sealed local data.

- [ ] **Step 4: Run continuity and sync regressions**

Run: `./scripts/local-env.sh python -m pytest client/tests/test_background_access_continuity.py client/tests/test_sync_worker.py client/tests/test_recovery.py -q`

Expected: PASS.

- [ ] **Step 5: Commit background continuity**

```bash
git add client/cloud/runtime.py client/sync/worker.py client/tests/test_background_access_continuity.py
git commit -m "feat: keep licensed sync active while UI locks"
```

## Task 9: Capture deterministic desktop evidence

**Files:**

- Create: `scripts/capture_seed_access_ui.py`
- Create: `docs/evidence/linear/RAY-100/seed-access-ui/README.md`
- Create: `docs/evidence/linear/RAY-100/seed-access-ui/activation.png`
- Create: `docs/evidence/linear/RAY-100/seed-access-ui/login.png`
- Create: `docs/evidence/linear/RAY-100/seed-access-ui/locked.png`
- Create: `docs/evidence/linear/RAY-100/seed-access-ui/license-suspended.png`

- [ ] **Step 1: Add deterministic capture states**

Use injected fake access/hardware adapters and a fixed clock. Capture 1440x900 standard and one 1280x720 long-copy state. Do not connect to cloud or physical hardware.

- [ ] **Step 2: Run the capture**

Run: `./scripts/local-env.sh python scripts/capture_seed_access_ui.py --output docs/evidence/linear/RAY-100/seed-access-ui`

Expected: four PNG files and a JSON manifest containing dimensions, state names, commit SHA, and `evidence_scope="simulated-access-ui"`.

- [ ] **Step 3: Inspect images**

Check no clipping, secret values, institution-search UI, customer-admin UI, or raw hardware serial. The suspended screen must allow Reports and Sync while disabling New Test.

- [ ] **Step 4: Run the client suite**

Run: `./scripts/local-env.sh python -m pytest client/tests -q --junitxml=docs/evidence/linear/RAY-100/pytest-seed-client-access.xml`

Expected: PASS.

- [ ] **Step 5: Commit client evidence**

```bash
git add scripts/capture_seed_access_ui.py docs/evidence/linear/RAY-100/seed-access-ui docs/evidence/linear/RAY-100/pytest-seed-client-access.xml
git commit -m "test: capture seed client access evidence"
```

## Client Plan Completion Gate

- [ ] Activation UI contains no institution search/create/join or customer-admin workflow.
- [ ] A replacement computer can log in without License transfer; the same bound hardware is still required to start a test.
- [ ] Missing/ambiguous stable hardware identity fails closed without invented identity.
- [ ] Local test License remains isolated from cloud credentials and production handoff.
- [ ] Policy matrix proves safe finalize/report/upload behavior for suspended/expired/offline states.
- [ ] Auto-lock does not interrupt active acquisition, finalization, refresh, heartbeat, or upload.
- [ ] `./scripts/local-env.sh python -m pytest client/tests -q` passes.
