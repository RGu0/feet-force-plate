# TechFlex Cloud Foundation

`techflex-cloud-foundation` provides the versioned, business-neutral boundary
for TechFlex desktop and cloud applications.  Its public surface is only the
symbols exported by `techflex_cloud_foundation`.

The package deliberately does **not** own application schemas, SQL, HTTP
routes, algorithms, reports, or executable remote updates.  Applications
provide adapters through the published protocols and retain ownership of their
own business model.

Security fixes are released as patch versions.  Signed trust bundles may rotate
verification keys and policy data, but cannot install or execute code.

The `server` extra contains only server-side dependency support.  Desktop
applications must never install database credentials, server pools, or License
private keys.

## Release evidence

The `Foundation release security baseline` CI job is required before a package
release. It verifies the locked environment, runs the vulnerability audit,
builds the wheel and source archive, and publishes a non-secret artifact
containing the CycloneDX dependency inventory, source revision, lock digest,
artifact SHA-256 values, and offline transport benchmark. The benchmark uses
one `SecureTransport` instance and compares it in the same CI invocation with
the preserved pre-extraction direct `httpx.Client` workload from revision
`6e76234`; comparison rejects a P95 regression above 5% or a peak-memory
regression above 10%.

The evidence records no activation codes, tokens, private keys, client data,
or raw frames. A signed trust-bundle update may change trust material or policy
data only; it cannot change executable package code.
