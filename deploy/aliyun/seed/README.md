# Seed deployment toolkit ownership

The seed service, migrations, backup/restore, smoke and deployment toolkit are
maintained in the published `techflex-cloud-foundation==0.9.5` source release.
This FeetForcePlate directory retains only the product public TLS bundle helper
`build-integration-public-bundle.sh` and this ownership note.

Run `./dev setup` (Windows: `pwsh -File dev.ps1 setup`) to synchronize the
locked wheel and cache the digest-verified published 0.9.5 sdist. Resolve its
developer source root without downloading anything (setup must have prewarmed
both dependencies and source; offline sync fails closed on a cache miss):

```bash
UV_OFFLINE=1 ./dev run python scripts/foundation_release_source.py --offline --print-root
```

The helper verifies both the archive and extracted tree and fails if the cache
is missing or modified. Read the following paths **under the returned source
root**, rather than looking for deleted tools in this repository:

- `docs/guides/seed-cutover-runbook.md`: release, cutover and rollback procedure;
- `deploy/aliyun/seed/README.md`: host layout, installation and diagnostic
  retention/OSS procedure;
- `deploy/aliyun/seed/` and `scripts/`: released deployment tools and smoke
  entrypoints, invoked only according to the release's manual and environment.

Source availability and passing consumer tests are not evidence of a host
operation. This adoption performs no deployment, migration, restore, activation
or upload. Parent desktop activation and real upload remain user gates.

Known release limitation: backup metadata enumerates migrations through `0019`,
while the source migration plan extends through `0022`. This adoption does not
repair that difference; do not treat the metadata list as proof that the full
plan was backed up, applied or restored. Keep the discrepancy explicit in any
separately authorized deployment/restore review. Historical plans and receipts
remain unchanged.
