# RAY-116 — Seed MVP access lifecycle evidence

## Verified locally

Implementation SHA: `29e198602cbb2f1078c7023dbb98572e4bcfc7e6`

```bash
./scripts/local-env.sh python -m pytest cloud/tests/test_seed_access_end_to_end.py -q
# 1 passed in 0.87s

./scripts/local-env.sh python scripts/verify_seed_access.py \
  --output docs/evidence/linear/RAY-116/seed-access-summary.json
# tenant_count: 10
```

The deterministic acceptance provisions ten synthetic institutions, each with
one account, License, physical-hardware identity placeholder, installation and
synthetic ingestion session. Each tenant sees its own single ingested session;
cross-tenant access is denied, and a signed context for an unprovisioned
eleventh tenant cannot read a provisioned tenant resource. Tenant 1 then changes from one active access
group to three and back to two while all three contribution records remain in
the same tenant history.

Negative evidence covers wrong audience, wrong hardware, activation replay,
refresh replay, concurrent hardware lease, suspended/expired/revoked new-test
denial, ungranted sensitive identity access, and rejection of the documented
local UI test License at the cloud boundary. The JSON contains only numbered
tenant slots and booleans—no raw activation code, password, token, account
lookup, hardware serial, subject identity, DSN, or signing material.

## Evidence boundary

This is synthetic software lifecycle and tenant-isolation evidence. The
“visible session” represents a generated data segment plus verified manifest;
it is not evidence of a physical force-plate capture, clinical report content,
operator usability, or a medically validated conclusion.

Still open until the deployment steps complete:

- live PostgreSQL migrations and the three application-role/RLS matrix;
- public 7443 TLS/network integration and certificate pinning;
- backup restore into a clean PostgreSQL/object-store instance;
- physical hardware identity and operator workflow;
- domain + public-CA certificate + port 443 for formal customer rollout;
- clinical validation and production/compliance release review.

## Current evidence matrix

| Criterion | State | Evidence |
|---|---|---|
| Provider-provisioned account/License activation | PROVEN_LOCAL | `cloud/tests/test_tenant_authentication.py` |
| Replacement computer, same License/hardware | PROVEN_LOCAL | `client/tests/test_seed_access_runtime.py` |
| Dynamic tenant 1 -> 3 -> 2 | PROVEN_LOCAL | `seed-access-summary.json` |
| Ten isolated synthetic ingestion lifecycles | PROVEN_LOCAL | `seed-access-summary.json` |
| Private immutable filesystem objects | PROVEN_LOCAL | `cloud/tests/test_filesystem_object_store.py` |
| Platform roles, masking and 15-minute grants | PROVEN_LOCAL | `RAY-103/platform-iam-summary.json` |
| Full repository regression | PROVEN_LOCAL | `pytest-full-seed-access.xml`: 726 tests, 0 failures, 1 skipped, 51.226 s |
| PostgreSQL role/RLS parity | PENDING_POSTGRES | skipped live test; three DSNs unavailable |
| Encrypted clean restore | PENDING_POSTGRES | `RAY-97/restore-exercise.md` |
| Aliyun 7443 lifecycle and restart | PENDING_ALIYUN | host prerequisites not installed |
| Physical force-plate identity | NEEDS_HARDWARE | no real device run in this evidence |
| Domain/public CA/443 | NEEDS_FORMAL_INGRESS | explicitly deferred commercial gate |

Implementation checkpoint for the full local regression:
`4122c781b222b4e0257c194db9bcda11b1aa8db6`.
