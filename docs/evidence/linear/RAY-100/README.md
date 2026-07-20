# RAY-100 Evidence — 终端激活纳管、联网门槛与本地功能开关

- Issue: `RAY-100`
- Title: 终端激活纳管、联网门槛与本地功能开关
- URL: https://linear.app/ray-app/issue/RAY-100/终端激活纳管联网门槛与本地功能开关
- Linear snapshot: `2026-07-20T09:54:33Z`
- Evidence refreshed: `2026-07-20T10:06:40Z`
- Status at implementation start: `In Progress`
- Milestone: `P5：商业运营`
- Priority: `Urgent`
- Relations: no declared blockers, blocked issues, related issues, duplicates, releases, or customer needs
- Baseline: `c0e4f38113453f2c517158347b499618ce19f6f6`
- RAY-97 server prerequisite: `d8466ead54cc25697185b2811c71937550f1b45b`
- RAY-99 sync prerequisite: `f76d042f598c0459ff57781f3b769fa379c497c2`
- RAY-100 implementation commit: `a4642125c887addf932dbf00acb67839dbc1a5fa`

## Acceptance snapshot and result

- [x] First online activation binds `tenant/site/terminal` and an optional preapproved DO-P4864 device in one reference/production transaction. The activation code is HMAC-indexed, row-locked, single-use, expiry-checked, installation-unique, idempotent for an identical replay, and audited without logging the code.
- [~] The returned short-lived terminal-bound identity supports silent authenticated API use. Real client startup storage/refresh and certificate enrollment are not implemented in this server-owned scope.
- [x] The periodic heartbeat contract is an operational allowlist. Unknown subject/report/raw-data fields are rejected and their values are not echoed.
- [x] Exactly 24 hours since last successful online contact remains allowed; more than 24 hours blocks a new test.
- [x] Exactly 50 pending sessions and exactly 2 GiB pending bytes each independently block a new test.
- [x] A gate never removes existing-report viewing, completed-report download, continued upload, or diagnostics. An in-progress test retains `FINISH_CURRENT_TEST`; `START_NEW_TEST` is withheld.
- [~] Ed25519 License signature, tenant/terminal binding, validity window, status/revocation, canonical feature flags, and cache serialization are automatically verified. Client secure cache/key rotation and a production License issuance backend are not integrated here.
- [x] Explicit clock rollback and invalid credential states require support.
- [~] Re-evaluating the pure policy after a fresh successful online time automatically clears the offline gate. Client network-monitor wiring is not implemented here.
- [~] A temporary authorization outage within the 24-hour window does not block a new test in the policy, and an already-created session can continue uploading after terminal revocation while its short-lived credential remains valid. Real acquisition/process behavior during an outage is not integration-tested.

`[x]` means repeatable automated evidence exists in this repository. `[~]` means the cloud/shared-contract part is complete but client or deployed integration evidence is missing.

## Implementation files and key decisions

- `cloud/device_management/service.py`, `cloud/device_management/__init__.py`
  - HMAC-protect activation-code lookup, consume a code through the repository, issue a short-lived terminal token, and record route-bound heartbeats.
- `cloud/api/app.py`, `cloud/api/errors.py`
  - Add the approved `POST /v1/terminals/enroll` and `POST /v1/terminals/{terminal_id}/heartbeats` surface, safe activation errors, and device-service dependency injection.
- `cloud/api/repository.py`
  - Deterministic reference adapter for one-time enrollment, device binding, terminal status, privacy-safe heartbeats, and idempotent replay.
  - Existing-session lookup permits controlled upload for a non-active terminal; new session creation and heartbeat still require `ACTIVE`.
- `cloud/api/postgres.py`
  - Production activation transaction uses a separate enrollment pool because the tenant is not trusted until the code resolves. It locks/consumes the code, creates terminal/device binding, writes idempotency and safe audit records atomically.
  - Authenticated heartbeat uses the normal tenant-scoped RLS transaction, validates active terminal/device binding, records the heartbeat, updates terminal health, and stores the idempotent response.
- `cloud/migrations/0001_p3_cloud_platform.sql`
  - Allows an enrollment code to prebind one approved tenant device with a composite tenant-aware foreign key.
- `shared/contracts/device_policy.py`, `shared/contracts/__init__.py`
  - Strict cacheable signed License, pinned Ed25519 verifier, feature flags, approved threshold defaults, clock rollback detection, and an explicit allowed-capability decision.
- `cloud/api/README.md`
  - Documents the isolated enrollment-role boundary and production composition.
- `cloud/tests/test_device_management.py`, `test_device_management_api.py`, `test_device_policy.py`, plus focused migration/ingestion regression additions
  - Cover single use, replay, expiry, token tamper/binding, heartbeat privacy, threshold boundaries, License tamper/revocation, safe capabilities, recovery reevaluation, and revoked-terminal upload semantics.

Key decisions:

- Activation codes are never stored or queried as plaintext by the service; a server-only HMAC digest is the lookup key.
- The main tenant API role keeps forced RLS and no `BYPASSRLS`. Pre-authentication code resolution requires a distinct, least-privilege enrollment pool; it must never serve authenticated tenant traffic.
- License signatures cover canonical JSON with normalized, sorted feature flags. A changed feature set invalidates the signature.
- License or connectivity policy can block only starting a new test. It cannot abort an active test or erase/view-block already collected data.
- Revocation blocks new sessions immediately, while an existing session may finish upload using a still-valid short-lived token. Credential expiry/recovery after revocation requires an explicit deployment policy and is not inferred here.

## Verification commands and results

Initial RED evidence:

```text
PYTHONPATH=. /private/tmp/feetforceplate-p3-venv/bin/python -m unittest cloud.tests.test_device_policy cloud.tests.test_device_management -v
ModuleNotFoundError: No module named 'shared.contracts.device_policy'
ImportError: cannot import name 'ActivationCodeInvalid'
Ran 2 tests; FAILED (errors=2)
```

Additional RED evidence was captured before each implementation boundary:

- API tests failed because `ServiceContainer` had no `devices` dependency.
- Migration test failed because `device.enrollment_codes` had no device prebinding field/FK.
- Revocation test failed because the reference repository rejected upload for an already-created session.
- Extreme retry overflow was fixed under RAY-99 and remains in the full regression suite.

Targeted GREEN evidence:

```text
PYTHONPATH=. /private/tmp/feetforceplate-p3-venv/bin/python -m unittest cloud.tests.test_device_policy -v
Ran 8 tests; OK

PYTHONPATH=. /private/tmp/feetforceplate-p3-venv/bin/python -m unittest cloud.tests.test_device_management -v
Ran 5 tests; OK

PYTHONPATH=. /private/tmp/feetforceplate-p3-venv/bin/python -m unittest cloud.tests.test_device_management_api -v
Ran 2 tests; OK

PYTHONPATH=. /private/tmp/feetforceplate-p3-venv/bin/python -m unittest cloud.tests.test_migration_contract -v
Ran 6 tests; OK
```

Full regression evidence:

```text
PYTHONPATH=. /private/tmp/feetforceplate-p3-venv/bin/python -m unittest discover -s cloud/tests -v
Ran 65 tests in 0.140s; OK
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

- one-time/expired/idempotent activation behavior and terminal/token binding;
- HMAC activation lookup and no raw code in error evidence;
- heartbeat contract privacy allowlist and no rejected value echo;
- token tamper/expiry behavior and active-terminal heartbeats;
- exact 24-hour, 50-session, and 2-GiB boundaries;
- safe-finish/report/upload/diagnostic capabilities under combined gates;
- Ed25519 License tamper, binding, revocation, time-window, feature, and cache round-trip behavior;
- time rollback/support decision and silent policy reevaluation after network recovery;
- new-session denial plus existing-session upload after revocation;
- migration shape, production code compilation, and all prior RAY-97/RAY-99 regressions.

Not verified here:

- live PostgreSQL 15 migration, isolated enrollment-role grants/BYPASSRLS audit, concurrent activation race, or real audit inspection;
- actual client OS secure storage, startup silent login, token/certificate rotation, signed License cache/key rotation, or revocation polling;
- actual client gate wiring at the “start test” command boundary;
- network monitor behavior and automatic unlock in a running process;
- real acquisition/report continuity during an authorization outage;
- pressure-device discovery/binding on hardware, manual operator recovery, or UI wording;
- production License issuance, Feature Flag administration, and upgrade/config rollback, which also depend on RAY-98 operations scope.

These missing client, live-database, hardware, and operational checks prevent `Done`. RAY-100 is eligible only for `In Review` after the implementation/evidence commits.

## Failures and limitations

- The production enrollment path deliberately requires a separate pre-authentication database role. Its exact grants and deployment isolation cannot be proven by source tests and must be reviewed in the real environment.
- Current terminal identity is a short-lived server HMAC token. It proves API contract binding, not device-held private-key possession or certificate attestation.
- Controlled upload after revocation lasts only while an already-issued token remains valid; post-expiry recovery must follow an explicit revocation-reason policy.
- No secrets, personal data, activation codes, raw pressure frames, or customer report data are stored in this evidence directory.
