# RAY-97 Evidence — 云端接入、原始数据存储与多租户隔离

- Issue: `RAY-97`
- URL: https://linear.app/ray-app/issue/RAY-97/云端接入原始数据存储与多租户隔离
- Linear snapshot: `2026-07-20T08:55:25Z`
- Status: `In Progress`
- Milestone: `P3：云端闭环`
- Priority: `Urgent`
- Relations: no declared blockers, blocks, duplicates, or related issues
- Implementation commit: `d8466ead54cc25697185b2811c71937550f1b45b`

## Acceptance snapshot

- [ ] Independent terminal identity, activation credential, and TLS boundary
- [ ] Session, segment, and final-manifest APIs with idempotency and digest-conflict detection
- [ ] Immutable raw segments in object storage; PostgreSQL indexes and states
- [ ] Validate tenant, terminal, session, segment index, and schema version on ingestion
- [ ] Mark ingestion complete only when the accepted segment set exactly matches the manifest
- [ ] Multi-tenant institutional isolation and least-privilege access
- [ ] Retention, backup, recovery, and audit strategy
- [ ] Security-domain separation for raw data, identity, reports, and logs
- [ ] Ingestion failures never pollute or silently overwrite accepted objects
- [ ] Privacy/compliance review for the actual deployment region

## Planned implementation and decisions

- `shared/contracts/`: strict versioned session, segment, manifest, event, and error contracts.
- `cloud/ingestion/`: immutable object-store adapter and exact manifest verifier.
- `cloud/api/`: authenticated FastAPI routes, tenant-bound repository, and stable error mapping.
- `cloud/migrations/0001_p3_cloud_platform.sql`: tenant-aware PostgreSQL schemas, constraints, RLS, and transactional Outbox.
- `cloud/tests/`: repeatable tenant-isolation, idempotency/conflict, missing-segment, manifest-gate, and partial-failure tests.

Tenant identity will come from the verified terminal token. Request bodies cannot choose `tenant_id`. A session can emit `session.ingested.v1` only in the same transaction that verifies and persists the exact manifest.

## Verification record

- Baseline `python3 -m unittest discover -s cloud/tests -v`: no baseline test package existed at commit `c0e4f38`.
- First dependency run failed inside the sandbox because the configured local proxy was blocked. After approved dependency installation, each implementation slice was rerun from an expected missing-module/behavior RED before GREEN.
- `PYTHONPATH=. /private/tmp/feetforceplate-p3-venv/bin/python -m unittest discover -s cloud/tests -v`: `38` tests passed, `0` failures at the RAY-97 pre-review checkpoint. Coverage includes tenant/header binding, cross-tenant denial, tenant/issuer/type-scoped external-ID HMAC and encryption, optional identity-vault encryption, consent lifecycle, exact schema and digest checks, same-index replay/conflict (including an injected database race), missing-segment query, invalid-quality/manifest gating, single Outbox effect, RLS migration contract, transaction-scoped tenant context, and object/database failure compensation.
- `PYTHONPATH=. /private/tmp/feetforceplate-p3-venv/bin/python -m compileall -q cloud shared`: passed at the pre-review checkpoint.
- `git diff --check`: passed at the pre-review checkpoint.

## Acceptance mapping at pre-review checkpoint

- Terminal identity: short-lived terminal-bound HMAC token verification and header/session cross-check are automated; online activation issuance and certificate/TLS deployment remain RAY-100/external evidence.
- Session/segment/manifest API: implemented and exercised through ASGI contract tests.
- S3/PostgreSQL: production adapters and migration implemented; deterministic object adapter and SQL contracts tested, live services not available.
- Ingestion validation: tenant, terminal, session, route/metadata index, schema, length, digest, totals, consent, and quality contexts are enforced.
- Completion status: approved repository state `INGESTED` means Linear's `INGESTED_COMPLETE`; it is written only with the exact verified manifest and one transactional Outbox event.
- Multi-tenant/minimum privilege: forced RLS policies and per-transaction tenant context are present; live role-matrix penetration testing is outstanding.
- Retention/backup/recovery/audit: tables and operator strategy are in `cloud/api/README.md`; production restore/reconciliation drill is outstanding.
- Security domains: identity vault, analysis profile, raw objects, and audit/log tables are separated; no report implementation was added.
- Failure safety: digest conflict never overwrites, and injected database failure removes only an unreferenced object.
- Privacy/compliance: code defaults minimize and encrypt identity data; jurisdiction-specific legal review is outstanding.

## Status vocabulary decision

Linear uses `INGESTED_COMPLETE` in one acceptance sentence, while the approved communication/database documents use `INGESTED`. The implementation keeps the approved `INGESTED` status and documents the semantic mapping instead of creating a second state.

## Verification boundary and limitations

- Automated in-memory/ASGI tests are not a real PostgreSQL, S3, TLS, or terminal-certificate deployment.
- Backup/restore drills, production least-privilege roles, and deployment-region privacy/compliance review require external environments and human approval.
- The implementation, tests, initial evidence, and plan are committed at `d8466ead54cc25697185b2811c71937550f1b45b`. This evidence-only follow-up records that immutable SHA.

## 2026-08-01 seed-access refresh

- `PROVEN_LOCAL`: private filesystem object store uses tenant-prefixed immutable
  keys, digest/size verification, 0700 directories, 0600 files, staging fsync and
  atomic rename (`cloud/tests/test_filesystem_object_store.py`).
- `PROVEN_LOCAL`: PostgreSQL access adapter has separate tenant, activation and
  Platform pools, forced tenant context and row locks; SQL/mocking contracts pass.
- `PROVEN_LOCAL`: 10 synthetic tenants each complete one isolated ingestion
  lifecycle (`RAY-116/seed-access-summary.json`).
- `PROVEN_LOCAL`: encrypted backup/restore assets enforce custom pg_dump,
  external age recipient, object manifest and separate empty restore target.
- `PENDING_POSTGRES`: migration/role/RLS parity test is the one skipped item in
  `RAY-116/pytest-full-seed-access.xml` because the live role DSNs do not yet exist.
- `PENDING_ALIYUN`: restore exercise remains explicitly pending in
  `restore-exercise.md`; regional privacy/compliance review also remains open.

No status change to Done is justified until live PostgreSQL, clean restore and
Aliyun seed evidence pass.

## 2026-08-03 Aliyun OSS least-privilege data-plane probe

- `PROVEN_ALIYUN_SEED`: the `aliyun-agentic` ECS instance obtained the expected
  RAM role through IMDSv2. No long-lived AccessKey was read, written, or used.
- `PROVEN_ALIYUN_SEED`: the role listed only the permitted `_staging/` prefix
  through the Beijing internal OSS endpoint. Listing the bucket root was denied.
- `PROVEN_ALIYUN_SEED`: a non-sensitive temporary object forced through the
  multipart upload path, copied from `_staging/` to `tenants/`, downloaded with
  a matching SHA-256, and deleted from both paths. The local probe file was also
  removed.
- `NOT_VERIFIED`: the operational role intentionally cannot read bucket
  encryption configuration; object metadata did not expose a KMS field to this
  probe. The administrator-configured SSE-KMS setting still needs independent
  configuration evidence.
- `NOT_VERIFIED`: `feetforceplate-seed` still composes `FileSystemObjectStore`.
  An OSS-adapter release, service restart/recovery, manifest ingestion, object
  lifecycle/retention, and region-specific privacy/compliance evidence remain
  required before this issue can leave `In Review`.
