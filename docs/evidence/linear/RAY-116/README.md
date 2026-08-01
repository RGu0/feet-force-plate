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
cross-tenant access is denied. Tenant 1 then changes from one active access
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
