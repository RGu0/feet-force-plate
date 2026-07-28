# P3 Cloud Platform and Data Synchronization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the P3 cloud control plane and ingestion loop for terminal identity, tenant-scoped subjects/consents, screening sessions, immutable segment upload, manifest verification, S3 storage, PostgreSQL RLS, transactional Outbox, and client synchronization contracts.

**Architecture:** A contract-first modular FastAPI application delegates terminal, subject, and ingestion behavior to focused services. PostgreSQL is the authoritative relationship/state store with per-transaction tenant context and RLS; S3-compatible storage owns immutable binary objects; only an atomically verified manifest may write `session.ingested.v1` to the Outbox. Repository and object-store protocols keep behavior independently testable with deterministic in-memory fakes while production adapters use `asyncpg` and `boto3`.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic v2, asyncpg, boto3/S3, cryptography AES-GCM, PostgreSQL SQL migrations, stdlib `unittest`, HTTPX ASGI contract tests.

## Global Constraints

- Preserve approved architecture and product language: health screening and risk提示, never disease diagnosis.
- Hardware baseline remains DO-P4864 48×64, 1,000,000 baud, approximately 12 Hz.
- Same `tenant_id + session_id + segment_index` and same SHA-256 is idempotent; a different SHA-256 is a non-retryable conflict and never overwrites.
- A manifest that has not passed complete set, size, frame-count, digest, tenant, consent, and validity checks must never emit `session.ingested.v1`.
- Tenant context comes from authenticated terminal credentials, never from a request body.
- Object keys contain only tenant and internal UUID identifiers; no identity plaintext or external subject ID.
- This plan does not implement metric algorithms, report templates, or client UI.
- Automated tests are not real PostgreSQL/S3 deployment, terminal certificate, device, or manual verification.

## Linear execution order

1. `RAY-97` cloud ingestion/storage/tenant isolation foundation.
2. `RAY-99` server sync and shared resume/final-consistency contracts; client SQLite/acquisition code remains outside this task's directory ownership.
3. `RAY-100` activation, heartbeat, License, and shared connectivity-gate contracts; client workflow wiring remains outside ownership.
4. `RAY-98` device/License operations backend only; no operations UI.

Each issue owns `docs/evidence/linear/<ISSUE-ID>/README.md`, advances alone in Linear, and receives an issue-scoped commit before the next issue starts.

---

### Task 1: Versioned shared cloud and client-sync contracts

**Files:**
- Create: `shared/__init__.py`
- Create: `shared/contracts/__init__.py`
- Create: `shared/contracts/cloud.py`
- Create: `shared/contracts/events.py`
- Create: `shared/contracts/client_sync.py`
- Test: `cloud/tests/test_contracts.py`

**Interfaces:**
- Produces: strict Pydantic request/response models for enrollment, heartbeat, subject resolution/creation, consent, session creation, segment metadata, manifest completion, missing segments, status, and event envelopes.
- Produces: `canonical_json_bytes(value) -> bytes`, `canonical_sha256(value) -> str`, `encode_segment_metadata(metadata) -> str`, `decode_segment_metadata(value) -> SegmentMetadata`, and `build_sync_plan(local, remote) -> SyncPlan`.

- [ ] **Step 1: Write failing contract tests**

```python
class ContractTests(unittest.TestCase):
    def test_segment_metadata_header_round_trips(self):
        encoded = encode_segment_metadata(self.metadata)
        self.assertEqual(decode_segment_metadata(encoded), self.metadata)

    def test_sync_plan_retries_only_missing_and_reports_digest_conflicts(self):
        plan = build_sync_plan(local_segments, remote_segments)
        self.assertEqual(plan.missing_indices, (1,))
        self.assertEqual(plan.conflicting_indices, (2,))
```

- [ ] **Step 2: Run tests and confirm RED**

Run: `python -m unittest cloud.tests.test_contracts -v`
Expected: import failure because `shared.contracts` does not exist.

- [ ] **Step 3: Implement strict versioned models and canonical helpers**

Use `ConfigDict(extra="forbid")`, UUID types, timezone-aware datetime validators, SHA-256 lowercase-hex validators, explicit missing-value states, and deterministic sorted-key JSON. `build_sync_plan` must never select a conflicting remote index for automatic overwrite.

- [ ] **Step 4: Run tests and confirm GREEN**

Run: `python -m unittest cloud.tests.test_contracts -v`
Expected: all contract tests pass.

### Task 2: PostgreSQL schemas, tenant RLS, idempotency, and Outbox migration

**Files:**
- Create: `cloud/migrations/0001_p3_cloud_platform.sql`
- Create: `cloud/api/postgres.py`
- Test: `cloud/tests/test_migration_contract.py`

**Interfaces:**
- Produces: `tenant_transaction(pool, tenant_id)` which opens a transaction and calls `set_config('app.tenant_id', tenant_id, true)` before tenant SQL.
- Produces: `PostgresPlatformRepository` implementing the repository contract used by later services.
- Database schemas: `iam`, `device`, `subject`, `screening`, and `ops`; tables include tenants/sites, terminals/devices/bindings/enrollments/heartbeats, subjects/external identifiers/analysis profiles/consents, sessions/segments/manifests/problems, idempotency records, and Outbox events.

- [ ] **Step 1: Write failing migration contract tests**

```python
def test_migration_declares_rls_and_ingest_uniqueness(self):
    sql = MIGRATION.read_text()
    self.assertIn("ENABLE ROW LEVEL SECURITY", sql)
    self.assertIn("UNIQUE (tenant_id, session_id, segment_index)", sql)
    self.assertIn("ops.outbox_events", sql)
```

- [ ] **Step 2: Run tests and confirm RED**

Run: `python -m unittest cloud.tests.test_migration_contract -v`
Expected: failure because the migration is absent.

- [ ] **Step 3: Implement forward-only migration and asyncpg repository**

The migration must use composite tenant-aware foreign keys where practical, checks for approved states, active external-ID uniqueness, idempotency key request digests, RLS `USING/WITH CHECK` policies based on `app.tenant_id`, and an unpublished Outbox index. Repository writes for manifest verification must lock the session, compare every manifest entry to verified segment rows, write the manifest, set `INGESTED`, and insert `session.ingested.v1` within one SQL transaction.

- [ ] **Step 4: Run migration contract tests and syntax/import checks**

Run: `python -m unittest cloud.tests.test_migration_contract -v && python -m compileall cloud/api/postgres.py`
Expected: tests pass and compilation succeeds.

### Task 3: Terminal activation identity and privacy-safe heartbeats

**Files:**
- Create: `cloud/device_management/__init__.py`
- Create: `cloud/device_management/service.py`
- Create: `cloud/api/auth.py`
- Test: `cloud/tests/test_device_management.py`

**Interfaces:**
- Produces: `TerminalTokenIssuer.issue(tenant_id, terminal_id, expires_at) -> str` and `.verify(token) -> TerminalContext` using a server-side HMAC key, expiry, key ID, and constant-time signature checks.
- Produces: `DeviceManagementService.enroll(request, idempotency_key)` and `.record_heartbeat(context, terminal_id, request, idempotency_key)`.
- Consumes: repository methods that atomically consume one activation-code hash, enforce installation uniqueness, and persist heartbeat/update terminal health.

- [ ] **Step 1: Write failing service tests**

```python
async def test_activation_code_is_single_use_and_token_is_terminal_bound(self):
    first = await service.enroll(request, "enroll-1")
    self.assertEqual(verifier.verify(first.access_token).terminal_id, first.terminal_id)
    with self.assertRaises(ActivationCodeInvalid):
        await service.enroll(request.model_copy(update={"installation_id": uuid4()}), "enroll-2")
```

Also assert an expired/tampered token is rejected and heartbeat serialization contains no subject identity, external ID, raw pressure, or report content fields.

- [ ] **Step 2: Run tests and confirm RED**

Run: `python -m unittest cloud.tests.test_device_management -v`
Expected: import failure for the missing service.

- [ ] **Step 3: Implement activation, token verification, and heartbeat behavior**

Hash activation codes before repository lookup, cross-check route and `X-Terminal-ID` against the token context, return a short-lived token, and update only approved health summary fields.

- [ ] **Step 4: Run tests and confirm GREEN**

Run: `python -m unittest cloud.tests.test_device_management -v`
Expected: all device-management tests pass.

### Task 4: Tenant-scoped subjects, external IDs, profiles, and immutable consent

**Files:**
- Create: `cloud/api/subject_service.py`
- Test: `cloud/tests/test_subject_consent.py`

**Interfaces:**
- Produces: `SubjectConsentService.resolve(context, request)`, `.create_subject(context, request, idempotency_key)`, `.create_consent(context, request, idempotency_key)`, and `.revoke_consent(context, consent_id, request, idempotency_key)`.
- Uses NFKC/trim/casefold normalization, HMAC-SHA256 lookup indexes, AES-256-GCM envelope ciphertext for external identifier storage, masked display values, and explicit `PROVIDED/NONE_REPORTED/DECLINED/UNKNOWN/NOT_APPLICABLE` states.

- [ ] **Step 1: Write failing tenant/consent tests**

```python
async def test_same_external_identifier_isolated_by_tenant(self):
    left = await left_service.create_subject(left_context, request, "left")
    right = await right_service.create_subject(right_context, request, "right")
    self.assertNotEqual(left.subject_uuid, right.subject_uuid)

async def test_consent_is_immutable_and_revocation_blocks_new_session(self):
    consent = await service.create_consent(context, request, "consent")
    await service.revoke_consent(context, consent.consent_record_id, revoke, "revoke")
    self.assertFalse(await repository.is_consent_active(context.tenant_id, consent.consent_record_id))
```

- [ ] **Step 2: Run tests and confirm RED**

Run: `python -m unittest cloud.tests.test_subject_consent -v`
Expected: import failure for the missing service.

- [ ] **Step 3: Implement subject and consent services**

Never log or place plaintext external IDs in object keys. Return only `subject_uuid`, masked identifier, profile, and conflict state. Consent creation validates subject/terminal tenancy, stores an immutable policy/purpose/category snapshot and evidence hash, and revocation adds a fact rather than editing consent content.

- [ ] **Step 4: Run tests and confirm GREEN**

Run: `python -m unittest cloud.tests.test_subject_consent -v`
Expected: all subject/consent tests pass.

### Task 5: Session creation and immutable S3 segment ingestion

**Files:**
- Create: `cloud/ingestion/__init__.py`
- Create: `cloud/ingestion/object_store.py`
- Create: `cloud/ingestion/service.py`
- Test: `cloud/tests/test_segment_ingestion.py`

**Interfaces:**
- Produces: `S3ObjectStore.stage_segment(...)`, `.put_manifest(...)`, and `.delete_if_unreferenced(...)` with immutable final keys under `tenants/{tenant_id}/sessions/{session_id}/...`.
- Produces: `IngestionService.create_session(...)`, `.put_segment(...)`, and `.list_segments(...)`.
- Consumes: authenticated context, versioned contracts, repository operations, and an async byte stream.

- [ ] **Step 1: Write failing ingestion tests**

```python
async def test_same_index_same_digest_is_idempotent(self):
    first = await service.put_segment(context, session_id, 0, metadata, chunks(payload))
    second = await service.put_segment(context, session_id, 0, metadata, chunks(payload))
    self.assertEqual(first.object_key, second.object_key)

async def test_same_index_different_digest_conflicts_without_overwrite(self):
    await service.put_segment(context, session_id, 0, metadata_a, chunks(payload_a))
    with self.assertRaises(SegmentDigestConflict):
        await service.put_segment(context, session_id, 0, metadata_b, chunks(payload_b))
    self.assertEqual(await objects.read(original_key), payload_a)
```

Also test digest/length mismatch, wrong tenant/session, consent revocation before session creation, and object/database partial-failure compensation.

- [ ] **Step 2: Run tests and confirm RED**

Run: `python -m unittest cloud.tests.test_segment_ingestion -v`
Expected: import failure for missing ingestion code.

- [ ] **Step 3: Implement streaming verification, immutable keys, and repository registration**

Stream into a spooled temporary file while computing SHA-256 and length; reject before finalization on mismatch. Check an existing segment first; same digest returns its acknowledgement, different digest records an ingest problem and conflict. For a race, repository registration is authoritative and the losing staged object is compensated without touching the accepted final object.

- [ ] **Step 4: Run tests and confirm GREEN**

Run: `python -m unittest cloud.tests.test_segment_ingestion -v`
Expected: all ingestion tests pass.

### Task 6: Final manifest verification, missing-segment query, and transactional Outbox

**Files:**
- Modify: `cloud/ingestion/service.py`
- Modify: `cloud/api/postgres.py`
- Test: `cloud/tests/test_manifest_outbox.py`

**Interfaces:**
- Produces: `IngestionService.complete_session(context, session_id, manifest, expected_sha256, idempotency_key)` and `.get_status(...)`.
- Repository completion result must report `INGESTED` only after exact index/digest/size/frame-count/totals validation and atomic Outbox insertion.

- [ ] **Step 1: Write failing manifest and Outbox tests**

```python
async def test_unconfirmed_or_missing_manifest_never_emits_ingested_event(self):
    await upload_only_segment_zero()
    with self.assertRaises(ManifestIncomplete):
        await service.complete_session(context, session_id, two_segment_manifest, digest, "complete")
    self.assertEqual(repository.events("session.ingested.v1"), [])

async def test_verified_manifest_emits_one_event_under_idempotent_replay(self):
    first = await service.complete_session(context, session_id, manifest, digest, "complete")
    second = await service.complete_session(context, session_id, manifest, digest, "complete")
    self.assertEqual(first, second)
    self.assertEqual(len(repository.events("session.ingested.v1")), 1)
```

Also test different manifest digest conflict, invalid local quality, total mismatch, and out-of-order contiguous indexes.

- [ ] **Step 2: Run tests and confirm RED**

Run: `python -m unittest cloud.tests.test_manifest_outbox -v`
Expected: missing completion behavior fails.

- [ ] **Step 3: Implement exact-set verification and Outbox gate**

Verify the canonical manifest hash before persistence. Store the manifest object, then let one repository transaction lock and compare the accepted segment set, update the session and manifest, and add one versioned event envelope. Any failure leaves the session non-`INGESTED` and produces no formal-analysis event.

- [ ] **Step 4: Run tests and confirm GREEN**

Run: `python -m unittest cloud.tests.test_manifest_outbox -v`
Expected: all manifest and Outbox tests pass.

### Task 7: FastAPI surface, production composition, and full contract verification

**Files:**
- Create: `cloud/__init__.py`
- Create: `cloud/api/__init__.py`
- Create: `cloud/api/errors.py`
- Create: `cloud/api/app.py`
- Create: `cloud/api/requirements.txt`
- Create: `cloud/api/README.md`
- Create: `cloud/tests/__init__.py`
- Create: `cloud/tests/fakes.py`
- Create: `cloud/tests/test_api_contract.py`

**Interfaces:**
- Produces: `create_app(container: ServiceContainer) -> FastAPI` exposing the approved `/v1` endpoints and OpenAPI models.
- Produces: production `ServiceContainer.from_environment()` composition for asyncpg, S3, secrets, token TTL, and supported schema versions; tests inject in-memory repository/object storage.

- [ ] **Step 1: Write failing ASGI contract tests**

```python
async def test_segment_conflict_maps_to_stable_409(self):
    response = await client.put(url, headers=headers_b, content=payload_b)
    self.assertEqual(response.status_code, 409)
    self.assertEqual(response.json()["error"]["code"], "E-SYN-409")

async def test_cross_tenant_session_reference_is_403(self):
    response = await other_tenant_client.get(f"/v1/sessions/{session_id}/status")
    self.assertEqual(response.status_code, 403)
```

Cover activation, token/header mismatch, heartbeat, subject resolve/create, consent create/revoke, session create, segment upload/replay/conflict, missing query, complete, and status. Assert error bodies contain no token, external identifier, or raw body.

- [ ] **Step 2: Install isolated dependencies and confirm RED**

Run: `python -m venv /private/tmp/feetforceplate-p3-venv && /private/tmp/feetforceplate-p3-venv/bin/pip install -r cloud/api/requirements.txt && PYTHONPATH=. /private/tmp/feetforceplate-p3-venv/bin/python -m unittest cloud.tests.test_api_contract -v`
Expected: API contract tests fail before routes/composition exist.

- [ ] **Step 3: Implement routes, dependency injection, error mapping, and operator README**

Map validation to 422, authentication to 401, tenant/terminal mismatch to 403, missing resources to 404, digest/idempotency conflict to 409, and temporary store errors to 503. Echo `X-Correlation-ID`; never accept body `tenant_id` as authority. Document migration application, required environment variables, S3 bucket permissions, activation-code provisioning boundary, and that automated fakes are not deployment verification.

- [ ] **Step 4: Run full verification**

Run: `PYTHONPATH=. /private/tmp/feetforceplate-p3-venv/bin/python -m unittest discover -s cloud/tests -v`
Expected: all tests pass with zero failures.

Run: `PYTHONPATH=. /private/tmp/feetforceplate-p3-venv/bin/python -m compileall cloud shared`
Expected: compilation succeeds.

Run: `git diff --check && git status --short`
Expected: no whitespace errors; only P3-owned paths and this plan are changed.
