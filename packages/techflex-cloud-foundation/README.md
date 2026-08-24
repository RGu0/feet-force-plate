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
