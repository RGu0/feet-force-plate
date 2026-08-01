# RAY-97 — Encrypted backup restore exercise

Status: **PENDING LIVE POSTGRESQL EXERCISE**

The reviewed backup/restore assets require PostgreSQL, `age`, an external
recipient/identity, and a clean target database/object root. Static asset tests
prove the intended safeguards but are not recorded as a successful restore.

The Aliyun deployment step must replace this section with:

- UTC timestamp and non-sensitive backup ID;
- source/target schema version set and implementation SHA;
- encrypted bundle SHA-256;
- clean target checks;
- PostgreSQL restore result and forced-RLS table count;
- representative object manifest digest results;
- tenant isolation, active/suspended License, and report/session metadata checks;
- explicit physical hardware, operator, clinical and formal-ingress exclusions.

Never record DSNs, passwords, private key paths, account names, activation
codes, hardware identities, subject identities, or raw object contents here.
