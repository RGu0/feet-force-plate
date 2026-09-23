# RAY-513 Suspended Valid Session Resume Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Block bare new-session registration under a suspended License while allowing authorized, previously captured valid sessions to register and upload safely.

**Architecture:** Issue server-bound, one-use capture grants while the License permits new tests; atomically assign one before local acquisition and carry it through the immutable upload handoff. The cloud registers a first session and consumes its grant or an audited legacy migration permit in one transaction; an existing session may replay by matching identity and digests without another grant. Both paths still require current `allow_upload=true`.

**Tech Stack:** Python 3.13, FastAPI/Pydantic, asyncpg/PostgreSQL with RLS, SQLite/AES-GCM client stores, httpx/SecureTransport, pytest, macOS/Windows CI.

**Spec:** `docs/superpowers/specs/2026-09-23-ray-513-suspended-valid-session-resume-design.md`

## Global Constraints

- Linear RAY-513 R4 is authoritative; this is the registered `suspended-valid-session-resume` scope only. Preserve PR #56 and RAY-99 evidence.
- `allow_upload=false` denies *all* session upload paths; suspended `allow_new_test=false` denies a bare first registration with HTTP 403 and no write.
- At most **50** unfinished grants per client installation; grants are prebound to one server UUID, do not expire solely for upload delay, and cannot be reassigned after cancellation, invalidation, or crash.
- The local **24-hour**, **50-session**, and **2 GiB** new-test gates remain; offline exhaustion blocks new tests, not history, safe close, or upload.
- Never treat client time, cached License, or a grant as cryptographic proof that capture preceded suspension. A legacy permit is manual, single-session, digest-bound, and auditable.
- Existing `SessionCreateRequest` JSON and its canonical digest stay unchanged. Secret grant/permit values travel only in redacted request headers and encrypted local state; no raw values in logs/evidence.
- Only run real project `setup`/`test`/`lint`/`build` via `python3 /Users/ruiguo/Developer/AI-Tools/git-worktree-linear-workflow/main/skills/initializing-agent-governance/scripts/project_command.py --project-root /Users/ruiguo/Developer/ProjectsOnFire/feet-force-plate/.worktrees/ray-513/suspended-valid-session-resume --action ACTION`. The manifest's committed argv selects `./dev ACTION` or Windows `dev.ps1`.
- No merge, scope completion, Linear Done, Aliyun deployment, or Windows-real-device acceptance claim from a passing local test alone.

## File map and interface sequence

1. `shared/contracts/capture_grants.py` owns request/response DTOs and the `SessionAuthorization` value object. It does not own persistence.
2. `cloud/migrations/0009_capture_grants.sql` owns tables, unique keys, RLS, grants, and audit references. `cloud/access_control/capture_grants.py` owns issuance, retirement, and permit approval rules; `cloud/api/postgres.py` and `cloud/api/repository.py` provide production/reference atomic adapters.
3. `cloud/ingestion/service.py` applies `allow_upload` before replay/new-registration decisions. `cloud/api/app.py` binds the explicit authorization headers and exposes grant/retirement/permit endpoints. `cloud/api/seed.py` wires the same service into production.
4. `client/cloud/access_client.py` fetches/retires grants. `client/app/institution_store.py` encrypts a local grant pool and atomically assigns a prebound UUID. `client/spool/state_store.py` stores the encrypted handoff authorization with the envelope. `client/hardware_integration/live_physical_workflow.py` and packaged composition connect assignment to real acquisition.
5. `client/sync/persistent_upload.py` computes the final manifest digest *before* first registration, submits authorization headers, and preserves blocked legacy data. `client/sync/runtime.py` continues recovery/scheduling without UI dependence.

All interfaces below are to be added in this order; if an existing fixture implements a protocol, update that fixture in the same task. Use short, scope-local commits after each green task. If the current `origin/master` advances, inspect it; do not rebase/reset automatically.

## Review Focus

- A lost 201 response followed by a different idempotency key must still replay the same session/grant and never create or charge a second session (Task 4).
- A grant assigned in one SQLite file but not yet handed to the spool must remain tied to its UUID after restart, not return to AVAILABLE (Tasks 6–7).
- A final manifest whose digest changes after registration must be rejected before analysis, while the original sealed bytes remain locally recoverable (Tasks 4 and 7).
- A current token bound to a replacement hardware/License may upload a historically authorized session only after original issuance facts match; current binding cannot rewrite those facts (Tasks 3–4).
- A migration request with insufficient or unresolved subject/consent evidence must fail closed, preserve the raw data, and leave an audit trail without copying PHI (Tasks 5 and 8).

---

### Task 1: Freeze the protocol and redaction boundary

**Files:** Create `shared/contracts/capture_grants.py`; modify `shared/contracts/__init__.py` only if this package exports peer contracts; test `cloud/tests/test_capture_grant_contracts.py` and `client/tests/test_access_client.py`.

**Interfaces:** Produce `CaptureGrant(session_id: UUID, token: SecretStr)`, `CaptureGrantBatchRequest(count: int)` (`1 <= count <= 50`), `CaptureGrantBatchResponse(grants: tuple[CaptureGrant, ...])`, `RetireCaptureGrantRequest(session_id: UUID, reason: str)`, `CaptureCredential(session_id: UUID, kind: Literal["grant", "migration_permit"], token: SecretStr)` for local assignment, and `SessionAuthorization(CaptureCredential)` with the additional final `manifest_sha256: str` field for network registration. `UploadMigrationPermitRequest` carries `tenant_id`, `account_id`, `license_id`, `installation_id`, `hardware_id`, `session_id`, `request_sha256`, `manifest_sha256`, `evidence_reference`, `reason`, `identity_conflict`, `reconciliation_reference`, and four reviewed-evidence flags for local `VALID`, immutable manifest, original consent, and historical authorization; `MigrationPermitResponse` carries `session_id` and a one-time `token: SecretStr`. `authorization.headers()` returns only `X-Capture-Authorization` and `X-Expected-Manifest-SHA256`. Define exact header syntax as `grant <opaque>` or `migration_permit <opaque>` and validate SHA-256 as 64 lowercase hex characters. These are transport DTOs, not authentication proofs.

- [ ] **Step 1: Add failing contract tests.** Exercise `CaptureGrantBatchRequest(count=0)`/`51` rejection, valid 50, invalid digest rejection, and `SessionAuthorization.headers()` exact keys. In `client/tests/test_access_client.py`, assert the access client never puts grant tokens in an exception string or response logging fixture.

  ```python
  with pytest.raises(ValidationError):
      CaptureGrantBatchRequest(count=51)
  credential = CaptureCredential(session_id=uuid4(), kind="grant", token=SecretStr("x" * 32))
  authorization = SessionAuthorization(**credential.model_dump(), manifest_sha256="a" * 64)
  assert authorization.headers()["X-Expected-Manifest-SHA256"] == "a" * 64
  assert "x" * 32 not in repr(authorization)
  ```
- [ ] **Step 2: Run the governed test action; expect failure.** Run `python3 /Users/ruiguo/Developer/AI-Tools/git-worktree-linear-workflow/main/skills/initializing-agent-governance/scripts/project_command.py --project-root /Users/ruiguo/Developer/ProjectsOnFire/feet-force-plate/.worktrees/ray-513/suspended-valid-session-resume --action test`; expect import/contract failures from the new tests.
- [ ] **Step 3: Add minimal DTOs.** For example:

  ```python
  class CaptureGrantBatchRequest(ContractModel):
      count: Annotated[int, Field(ge=1, le=50)]

  class CaptureCredential(ContractModel):
      session_id: UUID
      kind: Literal["grant", "migration_permit"]
      token: SecretStr

  class SessionAuthorization(CaptureCredential):
      manifest_sha256: Sha256Hex

      def headers(self) -> dict[str, str]:
          return {
              "X-Capture-Authorization": f"{self.kind} {self.token.get_secret_value()}",
              "X-Expected-Manifest-SHA256": self.manifest_sha256,
          }
  ```

  Import `SecretStr` from Pydantic and enforce at least 20 characters with a field validator; explicitly test `repr()` and errors. Keep `SessionCreateRequest` untouched.
- [ ] **Step 4: Rerun governed test and commit.** Require the new contract tests to pass and no unrelated failures; commit `feat(ray-513): define capture authorization contracts`.

### Task 2: Add durable server authorization schema

**Files:** Create `cloud/migrations/0009_capture_grants.sql`; modify migration registries only where `cloud/api/seed.py`/migration runner explicitly enumerates files; test `cloud/tests/test_migrations.py`, `cloud/tests/test_migration_contract.py`, and `cloud/tests/test_postgres_capture_grants.py`.

**Interfaces:** `screening.capture_grants` stores `(tenant_id, session_id, installation_id, account_id, license_id, hardware_id, token_sha256, issued_at, state, consumed_request_sha256, expected_manifest_sha256)` with `ISSUED/CONSUMED/RETIRED`; `screening.upload_migration_permits` stores the same immutable identity/digest bindings plus approver, reason, evidence reference and state; `ops.capture_authorization_audit` stores non-secret event references. A unique `(tenant_id, session_id)` and unique token digest prevent reassignment; transaction-level installation serialization enforces the 50 cap, not an unlocked count query.

- [ ] **Step 1: Add failing migration tests.** Assert both tables have tenant RLS with `FORCE`, no public/activation-role read, tenant role can issue/consume its grants but not sign owner permits, platform role can insert permits, and the 51st concurrent issuance for one installation is rejected. Model a second tenant's row as invisible under `app.tenant_id`.

  ```python
  row = await connection.fetchrow(
      "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE oid='screening.capture_grants'::regclass"
  )
  assert (row["relrowsecurity"], row["relforcerowsecurity"]) == (True, True)
  ```
- [ ] **Step 2: Run governed test; expect migration/schema assertions to fail.** Use the command in Task 1 Step 2.
- [ ] **Step 3: Add migration.** Use the repo's `BEGIN; ... COMMIT;` migration pattern, `CHECK (state IN ('ISSUED','CONSUMED','RETIRED'))`, unique digest/session indexes, and `ops.current_tenant_id()` policy. Lock the existing `device.client_installations` row before counting unfinished grants, so parallel replenishment serializes on one real row rather than relying on a hash. At minimum, the table and policy follow this shape; include the other identity/audit/permit fields listed in **Interfaces**:

  ```sql
  CREATE TABLE screening.capture_grants (
      tenant_id uuid NOT NULL,
      session_id uuid NOT NULL,
      installation_id uuid NOT NULL,
      account_id uuid NOT NULL,
      license_id uuid NOT NULL,
      hardware_id uuid NOT NULL,
      token_sha256 bytea NOT NULL UNIQUE,
      state text NOT NULL CHECK (state IN ('ISSUED','CONSUMED','RETIRED')),
      issued_at timestamptz NOT NULL DEFAULT now(),
      consumed_request_sha256 text,
      expected_manifest_sha256 text,
      PRIMARY KEY (tenant_id, session_id)
  );
  ALTER TABLE screening.capture_grants ENABLE ROW LEVEL SECURITY;
  ALTER TABLE screening.capture_grants FORCE ROW LEVEL SECURITY;
  CREATE POLICY capture_grants_tenant_isolation ON screening.capture_grants
      USING (tenant_id = ops.current_tenant_id())
      WITH CHECK (tenant_id = ops.current_tenant_id());
  ```

  Do not store plaintext tokens, consent details, raw segments, or reusable signed License documents.
- [ ] **Step 4: Rerun governed test and commit.** Include a PostgreSQL-backed test when the test DSNs are configured; commit `feat(ray-513): persist bounded capture authorizations`.

### Task 3: Issue and retire grants under current entitlement

**Files:** Create `cloud/access_control/capture_grants.py`; modify `cloud/api/app.py`, `cloud/api/seed.py`, `cloud/api/repository.py`, `cloud/api/postgres.py`; test `cloud/tests/test_capture_grant_api.py`, `cloud/tests/test_postgres_capture_grants.py`, `cloud/tests/test_tenant_access_ingestion.py`.

**Interfaces:** `CaptureGrantService.issue(context: IngestionPrincipal, count: int) -> CaptureGrantBatchResponse`; `retire(context, session_id, reason) -> None`. Adapter methods `issue_capture_grants(context, grants: tuple[CaptureGrant, ...])` and `retire_capture_grant(context, session_id, reason)` share the same server-generated UUID/token pair; adapters hash tokens before writing and never persist the cleartext. Issue only when current account, License, installation, and hardware ownership are valid and `allow_new_test=true`; no active HardwareLease is needed to *issue* or later upload. Retirement requires active License and an `ISSUED` row, never returns plaintext token. Both emit non-secret audit events.

- [ ] **Step 1: Write failing API tests.** Reuse the activated/suspended token fixture in `cloud/tests/test_tenant_access_ingestion.py`: active POST `/v1/access/capture-grants` returns unique UUID/token pairs; suspension makes it 403 with no new rows; 50 outstanding then request one more denies; retirement marks a canceled `ISSUED` row `RETIRED`, permits one replacement only after reactivation, and cannot retire a `CONSUMED` grant.

  ```python
  issued = await self.client.post(
      "/v1/access/capture-grants",
      headers=self.headers(self.session.access_token),
      json={"count": 1},
  )
  self.assertEqual(issued.status_code, 201, issued.text)
  self.assertEqual(len(issued.json()["data"]["grants"]), 1)
  ```
- [ ] **Step 2: Run governed test; expect route/service failures.** Use the command in Task 1 Step 2.
- [ ] **Step 3: Implement the service and route.** The route obtains `DataDependency` and passes its verified principal to the service. Generate `secrets.token_urlsafe(32)` and save only `hashlib.sha256(token.encode()).digest()`; generate `uuid4()` server-side. In PostgreSQL lock the installation row, recheck account/License/hardware entitlement, count `ISSUED`, insert only available slots, and append audit in the same transaction. Reference adapter mirrors those observable rules for fast tests.

  ```python
  async def issue(self, context: IngestionPrincipal, count: int) -> CaptureGrantBatchResponse:
      context.ensure_can_start_new()
      grants = tuple(
          CaptureGrant(session_id=uuid4(), token=secrets.token_urlsafe(32))
          for _ in range(count)
      )
      return await self._repository.issue_capture_grants(context, grants)
  ```
- [ ] **Step 4: Run governed test, inspect redacted logs, and commit.** Commit `feat(ray-513): issue and retire bounded capture grants`.

### Task 4: Make first registration and replay atomic

**Files:** Modify `cloud/ingestion/service.py`, `cloud/api/app.py`, `cloud/api/repository.py`, `cloud/api/postgres.py`, `cloud/api/errors.py` only if an existing 403/409 type is insufficient; test `cloud/tests/test_tenant_access_ingestion.py`, `cloud/tests/test_segment_ingestion.py`, `cloud/tests/test_postgres_capture_grants.py`.

**Interfaces:** Extend `IngestionService.create_session(context, request, idempotency_key, authorization: SessionAuthorization | None = None)` and both repository adapters identically. `POST /v1/sessions` accepts the two optional headers from Task 1; malformed or partial headers fail before a write. Store `expected_manifest_sha256` on a newly authorized session and compare it in `complete_manifest`. Existing session replay requires same tenant, canonical request digest, and—where recorded—same expected manifest digest; it never consumes a second grant. `get_status` and `list_segments` also enforce `ensure_can_upload()` so `allow_upload=false` cannot inspect or resume an existing upload.

- [ ] **Step 1: Add failing end-to-end tests.** Extend `cloud/tests/test_tenant_access_ingestion.py`: suspended bare first request is 403/no row; a grant issued before suspension allows the prebound UUID with correct request/manifest digest; wrong tenant/account/installation/hardware/session/digest or retired token rejects; delayed upload beyond 24 hours still works; `allow_upload=false` denies replay, status, segment listing, segment PUT, and completion. Simulate lost response, retry with another idempotency key, and assert one row/one consumption. Add two concurrent first-register calls against PostgreSQL and require exactly one inserted session. A replacement current License/hardware may authorize upload only when the recorded historical grant binding and request hardware still match.

  ```python
  headers = self.headers(suspended_access_token)
  headers.update({"Idempotency-Key": "retry-1", **authorization.headers()})
  first = await self.client.post("/v1/sessions", headers=headers, json=request.model_dump(mode="json"))
  self.assertEqual(first.status_code, 201, first.text)
  headers["Idempotency-Key"] = "retry-after-lost-response"
  replay = await self.client.post("/v1/sessions", headers=headers, json=request.model_dump(mode="json"))
  self.assertEqual(replay.status_code, 200, replay.text)
  self.assertTrue(replay.json()["data"]["idempotent_replay"])
  ```
- [ ] **Step 2: Run governed test; expect the suspended-valid and replay tests to fail.** Use Task 1's command.
- [ ] **Step 3: Move the gate to the right branch.** In service, call `context.ensure_can_upload()` first; let the repository find/validate an existing session before `ensure_can_start_new()`. For a first session under suspension, require and validate the grant or permit. In PostgreSQL use one `tenant_transaction`, `SELECT ... FOR UPDATE` authorization row, check `token_sha256` with constant-time comparison, identity fields and digests, insert session, mark authorization `CONSUMED`, insert idempotency/audit, then commit. Preserve the active legacy bare path. In-memory adapter must make the same decision atomically under a lock for concurrency tests. Add `ensure_can_upload()` to `get_status` and `list_segments`; retain it in `put_segment` and `complete_session`.

  ```python
  context.ensure_can_upload()
  existing = await repository.find_session(context, request.session_id)
  if existing is not None:
      return await repository.replay_session(context, request, idempotency_key, authorization)
  if not context.allow_new_test and authorization is None:
      context.ensure_can_start_new()  # existing 403 error, before any write
  return await repository.create_session(context, request, idempotency_key, authorization)
  ```

  Keep the final new/existing distinction inside the locked repository transaction; the early lookup is only a service-level decision hint, never the race-safety boundary.
- [ ] **Step 4: Bind completion.** In `complete_manifest`, compare the uploaded `canonical_sha256(manifest)` against the registration's stored expected digest before storing a completion receipt. Reject mismatch without deleting local source bytes or accepting analysis.
- [ ] **Step 5: Rerun governed tests and commit.** Commit `fix(ray-513): authorize suspended first registration and replay`.

### Task 5: Add owner-approved legacy migration permits

**Files:** Modify `cloud/access_control/capture_grants.py`, `cloud/api/app.py`, `cloud/api/seed.py`, `cloud/api/repository.py`, `cloud/api/postgres.py`; test `cloud/tests/test_capture_grant_api.py`, `cloud/tests/test_platform_api.py`, `cloud/tests/test_postgres_capture_grants.py`.

**Interfaces:** `CaptureGrantService.approve_migration(context: PlatformAccessContext, request: UploadMigrationPermitRequest) -> MigrationPermitResponse`. Request binds final reconciled tenant, account, historical License/installation/hardware, UUID, canonical request SHA-256, final manifest SHA-256, nonempty evidence reference and reason. It also carries a reviewed-evidence checklist with `VALID`, immutable segment manifest, original consent, and retained License or issuance audit; unresolved identity/consent prohibits approval. Only `PlatformRole.OWNER` may call `POST /v1/platform/upload-migration-permits`. Return the one-use secret once; persist digest only and append approver/reason/evidence-reference audit.

- [ ] **Step 1: Add failing tests.** `OPERATIONS`/`SUPPORT`/tenant token are 403; missing reason, empty evidence, unresolved identity mapping, and missing historic authorization evidence fail closed and produce a denial audit. OWNER approval returns a permit that works only for the bound tenant/session/two digests; replay of the same cloud session succeeds, a second session or changed digest does not consume it.

  ```python
  denied = await client.post(
      "/v1/platform/upload-migration-permits",
      headers=operations_headers,
      json=reviewed_request.model_dump(mode="json"),
  )
  assert denied.status_code == 403
  assert repository.permit_count(reviewed_request.session_id) == 0
  ```
- [ ] **Step 2: Run governed test; expect route and authorization failures.** Use Task 1's command.
- [ ] **Step 3: Implement review/permit flow.** Verify role explicitly as `PlatformRole.OWNER`, require a persisted RAY-99 reconciliation reference before final digest when identity conflicts exist, and store only evidence URI/ref plus hashes. Use a platform-privileged transaction for approval and the tenant transaction from Task 4 for consumption; never write raw PHI or token to `ops.audit_logs`.

  ```python
  if PlatformRole.OWNER not in context.roles:
      raise TenantAccessDenied("platform owner approval required")
  if request.identity_conflict and request.reconciliation_reference is None:
      raise RequestContractError("reconciled identity evidence is required")
  permit_token = secrets.token_urlsafe(32)
  await repository.insert_migration_permit(
      context, request, hashlib.sha256(permit_token.encode()).digest()
  )
  return MigrationPermitResponse(session_id=request.session_id, token=permit_token)
  ```
- [ ] **Step 4: Rerun governed tests and commit.** Commit `feat(ray-513): require owner-audited legacy permits`.

### Task 6: Bind preissued UUID to real local acquisition

**Files:** Modify `client/cloud/access_client.py`, `client/app/institution_store.py`, `client/hardware_integration/live_physical_workflow.py`, packaged institution composition under `client/app/` at the call site of `InstitutionSessionPort`; test `client/tests/test_access_client.py`, `client/tests/test_institution_store.py`, `client/tests/test_seed_access_runtime.py`, `client/tests/test_ray_99_packaged_upload_runtime.py`.

**Interfaces:** `CloudAccessClient.issue_capture_grants(access_token, count)` and `.retire_capture_grant(access_token, session_id, reason)` use Task 1 contracts. `InstitutionLocalStore.add_capture_grants(tenant_id, installation_id, grants)` encrypts the token, rejects duplicate/mismatched UUIDs, and stores `AVAILABLE/ASSIGNED/BURNED/RETIRED`. `InstitutionLocalStore.create_session(...)` takes the existing participant/protocol plus active tenant/installation binding; it selects one AVAILABLE grant and inserts `institution_sessions` with that prebound UUID in **one** SQLite transaction. `capture_credential(session_id) -> CaptureCredential` returns the encrypted grant reference only for that same session. `CaptureGrantExhausted` is the local new-test-only exception. Legacy sessions retain their existing UUID and lack a grant.

- [ ] **Step 1: Write failing local tests.** Insert one grant, create a session, assert returned UUID equals grant UUID; second session fails when pool empty without an institution session row; forced INSERT failure leaves grant AVAILABLE. After `mark_incomplete`, `INVALID`, or crash/reopen, the grant remains assigned/burned and cannot seed a different session. Test 50 local slots, tenant/installation mismatch, encrypted SQLite bytes absent plaintext token, and new-test-only exhaustion.

  ```python
  store.add_capture_grants(tenant_id, installation_id, (grant,))
  assert UUID(store.create_session(participant, protocol, tenant_id, installation_id)) == grant.session_id
  with pytest.raises(CaptureGrantExhausted):
      store.create_session(participant, protocol, tenant_id, installation_id)
  assert store.capture_credential(str(grant.session_id)).session_id == grant.session_id
  ```
- [ ] **Step 2: Run governed test; expect local assignment failures.** Use Task 1's command.
- [ ] **Step 3: Add local schema and assignment.** Add a dedicated `institution_capture_grants` table with unique `(tenant_id, installation_id, session_id)` and ciphertext; use `with self.db:` to UPDATE one AVAILABLE row by primary key and INSERT the matching institution session before commit. Preserve old UUID generation only for explicitly recognized pre-protocol legacy data; new formal acquisition must fail closed without a grant. Fetch/replenish only under current valid License and available network, without coupling background uploads to replenishment.

  ```python
  with self.db:
      row = self.db.execute(
          "SELECT session_id FROM institution_capture_grants "
          "WHERE tenant_id=? AND installation_id=? AND state='AVAILABLE' "
          "ORDER BY issued_at, session_id LIMIT 1",
          (tenant_id, installation_id),
      ).fetchone()
      if row is None:
          raise CaptureGrantExhausted("new test requires a preissued grant")
      session_id = str(row[0])
      self.db.execute(
          "UPDATE institution_capture_grants SET state='ASSIGNED' WHERE session_id=?",
          (session_id,),
      )
      self.db.execute(
          "INSERT INTO institution_sessions VALUES (?,?,?,?)",
          (session_id, context.subject_uuid, "ACQUIRING", encrypted_payload),
      )
  ```
- [ ] **Step 4: Connect the real workflow and run governed test.** Keep the existing HardwareLease and local 24h/50/2GiB start gates before entering acquisition. Commit `feat(ray-513): bind local capture to preissued session grant`.

### Task 7: Persist authorization through VALID handoff and upload

**Files:** Modify `client/spool/state_store.py`, `client/spool/session_commit.py`, `client/hardware_integration/live_physical_workflow.py`, `client/sync/persistent_upload.py`, `client/sync/runtime.py` only where composition changes; test `tests/spool/test_valid_session_commit.py`, `tests/spool/test_state_store.py`, `client/tests/test_p3_persistent_upload.py`, `client/tests/test_ray_99_packaged_upload_runtime.py`.

**Interfaces:** `StateStore.commit_valid_session(..., upload_credential: CaptureCredential | None = None)` encrypts the exact session-bound credential in `sync_handoffs` in the same transaction as the immutable envelope and segment rows. `StateStore.sync_handoff_credential(session_id)` restores it. `IngestionClient.create_session(access_token, request, idempotency_key, authorization: SessionAuthorization | None)` and `HttpIngestionClient` send Task 1 headers. `PersistentUploadQueue._upload_handoff` builds the final cloud `SessionManifest` and SHA-256 from sealed local bytes **before** `create_session`; persist that **cloud manifest** digest separately from the existing local promoted-file `manifest_sha256`, then send the cloud digest in registration and completion.

- [ ] **Step 1: Write failing durability and queue tests.** The same `session_id`/token survives reopen and retry; an authorization for another UUID is rejected at handoff; canceled/invalid sessions never reach `READY_FOR_NETWORK`; a network timeout after cloud registration retries with identical headers and key; a modified sealed segment changes the digest and blocks locally before first registration. For a legacy no-grant handoff under suspension, assert `BLOCKED`/manual-migration-needed and unchanged raw files. Exercise the real `PersistentUploadQueue`, not only direct API methods.

  ```python
  outcome = queue.upload_next(token_provider)
  assert outcome is UploadCycleOutcome.BLOCKED  # legacy first registration, no permit
  assert sealed_segment_path.read_bytes() == original_sealed_bytes
  assert store.sync_handoff_state(session_id) == "BLOCKED"
  ```
- [ ] **Step 2: Run governed test; expect handoff/queue failures.** Use Task 1's command.
- [ ] **Step 3: Add SQLite migration 10 and encrypted handoff.** Keep `SCHEMA_VERSION` monotonic and the migration backward-compatible with old handoffs. `commit_valid_session` verifies `UUID(session_id) == envelope.session_id` and grant's bound UUID before inserting; store ciphertext with context `capture_authorization:{session_id}`. Add nullable `expected_cloud_manifest_sha256` to `sync_handoffs`; set it once before first network registration from sealed bytes, and reject a later different value. Do not compare it to the existing local promoted-file digest. Never rederive historical identity from current UI or License.

  ```python
  if upload_credential is not None and upload_credential.session_id != UUID(session_id):
      raise ValueError("capture authorization session mismatch")
  encrypted_authorization = self._codec.encrypt(
      upload_credential.model_dump_json().encode(),
      context=f"capture_authorization:{session_id}",
  ) if upload_credential is not None else None
  ```

- [ ] **Step 4: Reorder queue and transport.** Construct the same `SessionManifest` currently used for completion before `create_session`; persist/compare its digest through `record_expected_cloud_manifest_sha256`; then pass `SessionAuthorization(kind, token, digest)`. Keep current subject/consent idempotency and resume logic. Ensure `HttpIngestionClient`'s legacy 422 retry never drops authorization headers or mutates the canonical body digest.

  ```python
  local = self._local_segments(handoff, envelope)
  manifest = self._manifest_for(handoff, local)
  cloud_digest = canonical_sha256(manifest)
  self._store.record_expected_cloud_manifest_sha256(handoff.session_id, cloud_digest)
  credential = self._store.sync_handoff_credential(handoff.session_id)
  authorization = SessionAuthorization(**credential.model_dump(), manifest_sha256=cloud_digest) if credential else None
  self._client.create_session(access_token, envelope.session_request(),
                              session_key(envelope), authorization)
  ```
- [ ] **Step 5: Run governed tests and commit.** Commit `feat(ray-513): carry capture authorization through durable upload`.

### Task 8: Reconcile pre-protocol captures without rewriting evidence

**Files:** Modify `client/app/institution_store.py`, `client/spool/state_store.py`, `client/sync/persistent_upload.py`; add `client/tests/test_legacy_migration_handoff.py`; update `docs/modules/08-subject-consent.md` in Task 9.

**Interfaces:** A local `LegacyMigrationBinding` records original session UUID, original immutable envelope hash, final RAY-99 reconciled subject/consent IDs, final request digest, final manifest digest, approval reference, and encrypted permit. `attach_legacy_migration_binding(session_id, binding)` never edits the original envelope or consent evidence. Queue uses the reconciled request only when binding plus permit agree with all final digests; otherwise it remains blocked for operator action.

- [ ] **Step 1: Add failing tests.** No-grant old VALID session with no binding stays blocked and raw bytes remain; mismatched consent/subject remains blocked; approved mapping to new consent persists across restart while original envelope hash is unchanged; a permit for the pre-reconciliation digest cannot upload the changed request. Denied approval leaves local artifacts and an operator-visible reason code.

  ```python
  original_digest = canonical_sha256(store.sync_handoff_envelope(session_id))
  store.attach_legacy_migration_binding(session_id, approved_binding)
  assert canonical_sha256(store.sync_handoff_envelope(session_id)) == original_digest
  assert store.legacy_migration_binding(session_id).final_request_sha256 == approved_binding.final_request_sha256
  ```
- [ ] **Step 2: Run governed test; expect migration-binding failures.** Use Task 1's command.
- [ ] **Step 3: Add append-only local binding.** Encrypt permit with existing `SensitiveBlobCodec`; require RAY-99's actual persisted identity/consent reconciliation reference, not a free-text assertion. If that prerequisite is absent in the current branch, stop this task and report a RAY-99 dependency; do not invent a parallel subject-merge algorithm or alter the original consent.

  ```python
  if binding.original_envelope_sha256 != canonical_sha256(original_envelope):
      raise UploadConflict("legacy evidence changed")
  if binding.final_request_sha256 != canonical_sha256(reconciled_request):
      raise UploadConflict("reconciled request differs from approved permit")
  if binding.final_manifest_sha256 != canonical_sha256(manifest):
      raise UploadConflict("manifest differs from approved permit")
  ```
- [ ] **Step 4: Rerun governed tests and commit.** Commit `feat(ray-513): resume approved legacy upload without evidence rewrite` only when the prerequisite is met.

### Task 9: Documentation, governed validation, and release handoff

**Files:** Modify `docs/产品需求文档_PRD.md`, `docs/modules/05-sync-upload.md`, `docs/modules/08-subject-consent.md`, `docs/superpowers/specs/2026-08-11-ray-99-packaged-upload-runtime-design.md`; inspect `docs/通信接口设计文档.md`, `docs/架构设计文档.md`; write scoped doc-sync and test evidence under `.project-context/evidence/ray-513/suspended-valid-session-resume/` through the governance workflow.

**Interfaces:** No new runtime API. Deliver a traceable requirement-to-test matrix and exact-commit evidence. Shared context copies are updated only after comparing content and recording the synchronization decision; never overwrite an unrelated changed document.

- [ ] **Step 1: Add the acceptance matrix to the scope evidence.** Rows: bare 403/no persistence; active grant issuance/limit/retirement; suspended first registration/replay; `allow_upload=false`; grant mismatch/parallel use; 24h/50/2GiB gates; restart and delayed upload; legacy permit denial/approval; real queue; schema RLS; redacted logs. Record actual test names and result paths, not inferred passes.
- [ ] **Step 2: Synchronize docs.** Explain the 50-grant risk window, no server expiry, manual legacy exception, and RAY-99 consent dependency. Review interface/architecture docs and record either exact edits or why unchanged. Preserve original historical design/evidence.
- [ ] **Step 3: Run governed `test`, `lint`, and `build` on this worktree.** Invoke `project_command.py --project-root ... --action test`, then `lint`, then `build` with the exact path in Global Constraints. Do not substitute direct pytest/ruff or a different venv when preflight fails. On Windows use the same wrapper; the committed manifest chooses `dev.ps1`.
- [ ] **Step 4: Commit docs/evidence and push.** Inspect `git diff --check`, the complete branch diff, secret/log redaction, scope registration and requirement revision R4. Commit `docs(ray-513): align capture grant and legacy upload contracts`; push the registered branch without force.
- [ ] **Step 5: Review and release gates.** Open/link the one scope PR once GitHub write access is available, get review/CI and use `review-and-validate-pr` before merge. Only after the exact corrective PR is merged may the release owner build an explicit RAY-120 D10 candidate and run controlled Aliyun seed tests for suspended bare 403, authorized valid first registration/replay, permit deny/approve and full live acceptance. Keep RAY-513/RAY-120 In Progress until their governed receipts and parent acceptance pass; do not make deployment a side effect of this plan's local execution.

## Execution stop conditions

- Stop if Linear R4 or this scope registration changes, if a required RAY-99 identity/consent reconciliation artifact does not exist, or if grant issuance cannot be made atomic at the database boundary.
- Stop before external release or merge if PR creation remains blocked by GitHub authorization. A pushed branch is reviewable but is not a PR, merge, or acceptance receipt.
- Never delete/rewrite local raw captures, historical consent, old requirement revisions, PR #56 evidence, or unrelated dirty worktree files to make the tests pass.
