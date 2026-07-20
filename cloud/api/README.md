# FeetForcePlate Cloud API (P3)

This package implements the institution-facing cloud ingestion boundary for health screening and risk提示. It does not implement disease diagnosis, metric algorithms, report templates, public report links, or client UI.

## Runtime baseline

- Python 3.11+
- PostgreSQL 15+ (the migration uses `UNIQUE NULLS NOT DISTINCT`)
- S3-compatible object storage with versioning and server-side KMS encryption
- TLS 1.2+ terminated by the deployment ingress; production must reject direct plaintext HTTP

Install dependencies into an isolated environment:

```bash
python -m venv .venv-cloud
.venv-cloud/bin/pip install -r cloud/api/requirements.txt
```

Apply `cloud/migrations/0001_p3_cloud_platform.sql` with a migration role before the API role starts. The API role must not own tenant tables or receive `BYPASSRLS`. Enrollment-code provisioning is an administrative operation and uses a separate audited role; the unauthenticated enrollment endpoint and License lifecycle are completed under RAY-100/RAY-98.

## Application composition

The transport is intentionally dependency-injected. A deployment bootstrap creates one `asyncpg.Pool`, one S3 client, and the server-only secrets, then composes:

```python
repository = PostgresPlatformRepository(pool)
objects = S3ObjectStore(s3_client, bucket=raw_bucket, kms_key_id=kms_key_id)
ingestion = IngestionService(
    repository,
    objects,
    supported_payload_schemas={"raw-segment/1"},
    supported_manifest_schemas={"session-manifest/1"},
)
subjects = SubjectConsentService(repository, identity_protector)
app = create_app(ServiceContainer(
    ingestion=ingestion,
    token_issuer=terminal_token_issuer,
    subjects=subjects,
))
```

Secrets must come from a secret manager and never from source control or request payloads:

- terminal-token signing key and key ID;
- external-identifier HMAC query key;
- identity AES-256-GCM key and key version;
- PostgreSQL credential;
- S3/KMS credentials.

## Security and isolation

- `tenant_id` is derived from the verified short-lived terminal token. Request bodies cannot choose a tenant.
- `X-Terminal-ID` is cross-checked against the token and the session owner.
- Every PostgreSQL application transaction calls `set_config('app.tenant_id', ..., true)` before tenant SQL; RLS is enabled and forced on tenant tables.
- External identifiers are NFKC-normalized, indexed by keyed HMAC, and stored as AES-256-GCM ciphertext. Optional name/contact fields use the separate identity-vault table and are never passed to ingestion/analysis objects.
- Object keys contain only tenant/internal UUIDs, segment indexes, and digest prefixes.
- Error responses use an allowlist of safe context and never echo bearer tokens, external identifiers, raw bodies, or report content.
- Formal analysis is triggered only by `session.ingested.v1`, written in the same PostgreSQL transaction that verifies the exact segment set and marks the approved `INGESTED` state. Linear's phrase `INGESTED_COMPLETE` maps to this approved documented state; no second status vocabulary is introduced.

## S3 permissions

The ingestion role needs only bucket-scoped `PutObject`, `GetObject/HeadObject`, `CopyObject`, and cleanup `DeleteObject` for:

```text
_staging/{tenant_id}/{session_id}/*
tenants/{tenant_id}/sessions/{session_id}/segments/*
tenants/{tenant_id}/sessions/{session_id}/manifests/*
```

Use separate buckets or access points for raw data, reports, diagnostics/logs, and identity backups. The analysis role can read verified raw objects but cannot access the identity vault.

## Recovery, retention, and audit operations

- Enable PostgreSQL continuous archiving/PITR and S3 versioning across failure domains. Production release evidence must include a restore into an isolated account and a manifest/object reconciliation run.
- A scheduled reconciler must report: staging objects past TTL, final objects without database references, database references without objects, tenant-prefix mismatches, and `INGESTED` sessions without exactly one unpublished/published ingestion event.
- Staging objects use a short quarantine lifecycle. Accepted raw segments are governed only by versioned `ops.retention_policies` and audited `ops.data_disposition_jobs`; upload errors never delete an accepted object.
- Identity access, cross-tenant denials, enrollment, configuration, export/support access, retention changes, and disposition results are appended to `ops.audit_logs` with safe context.
- Privacy/compliance requirements and retention periods must be approved for the actual deployment region; this repository deliberately contains no invented period.

## Verification boundary

Run local automated verification with:

```bash
PYTHONPATH=. /private/tmp/feetforceplate-p3-venv/bin/python -m unittest discover -s cloud/tests -v
PYTHONPATH=. /private/tmp/feetforceplate-p3-venv/bin/python -m compileall -q cloud shared
git diff --check
```

These tests use deterministic in-memory adapters plus SQL/transaction contract checks. They do not prove a live PostgreSQL migration, RLS role matrix, S3/KMS policy, TLS ingress, terminal certificate, backup restore, load target, or regional privacy review.
