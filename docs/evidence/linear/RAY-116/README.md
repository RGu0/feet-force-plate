# RAY-116 — Seed MVP access lifecycle evidence

## Verified outcomes

Lifecycle and restore evidence release:
`ddea38b10dfe5ff26b73b2354895b9bb257acc4b`.

- Local full regression: `723 passed, 1 skipped`; the single local skip is the
  live PostgreSQL DSN test executed separately on Aliyun.
- Deterministic local lifecycle: ten isolated synthetic institutions plus an
  unprovisioned eleventh context; tenant 1 expands from one access group to
  three and contracts to two without moving or deleting tenant history.
- Aliyun lifecycle: provider provisioning, activation, replacement computer,
  hardware lease exclusion, heartbeat, session creation, License suspension,
  continued in-flight upload, restore, invalid-login safety, platform/tenant
  token separation, service/PostgreSQL restart, and historical session access.
- Native PostgreSQL parity: four tests, zero failures/errors/skips, covering
  the three application pools, least-privilege grants, activation atomicity,
  hardware projection, License lifecycle, Platform support grants, and dynamic
  access-group history.
- Encrypted restore: newest age-encrypted bundle restored into a separate
  database and object root; four object digests, six tenants, twelve Licenses,
  and 38 forced-RLS tables verified. Production counts were unchanged and all
  temporary database/object/private-key material was removed.
- Network: only 7443 is reachable among tested service ports; 5432 and 8743
  remain loopback-only, while 80 and 443 are closed.
- Follow-up deployment: release `0a049890af6e905ccc05d5e1f40d034e131f366e`
  is ready with the backup timer active; its newly generated encrypted bundle
  passed a standard SHA-256 sidecar check.

## Evidence files

| Evidence | Result |
|---|---|
| `seed-access-summary.json` | 10+1 local tenant isolation and dynamic 1 -> 3 -> 2 |
| `pytest-full-seed-access.xml` | 723 passed, 1 skipped locally |
| `aliyun-seed-summary-ddea38b.json` | live lifecycle and restart, secrets excluded |
| `aliyun-seed-summary-ddea38b-postgres.xml` | 4 PostgreSQL tests, 0 failures/errors/skips |
| `restore-drill-ddea38b.json` | encrypted clean restore and cleanup verified |
| `network-boundary-ddea38b.json` | public/internal port boundary and TLS readiness |
| `deployment-0a04989.json` | follow-up release health, listeners, timer and backup sidecar verification |

The PostgreSQL XML is a redacted copy of source SHA-256
`018cb889aae083177fdf29795f506f0d793d0d99290ba4afb7b6b735959e8ede`;
only the internal host name was replaced. The live JSON SHA-256 is
`54dbab3932f166a3e28434f59e39f9b3022c1c8acff2c89bd818d50ff9c4584e`.

## Evidence boundary

The hardware identities and acquisition payload in these automated checks are
synthetic. This evidence does not prove a physical DO-P4864 run, operator
acceptance, clinical validity, or formal production/compliance release.

The MVP ingress currently uses a pinned self-signed certificate on port 7443.
A customer domain, public-CA certificate and standard port 443 remain explicit
commercial-rollout gates. The SSH post-quantum key-exchange warning is also a
separate host-hardening item; it did not affect HTTPS/API verification.
