# Local Controlled Integration Fault Lab Design

## Purpose

RAY-428 needs repeatable server-side fault evidence without placing a fault
endpoint, test identity, or test data on the remote integration service.  This
design adds a Windows-hosted lab that exercises the existing persistent
`cloud.api.seed` composition through TLS and retains its test-only state across
an application process restart.

## Decision

The lab reuses `SeedSettings` and `build_seed_app`; it does not introduce a
second ingestion implementation or an in-memory substitute.  PostgreSQL is
the required local state service, and the existing filesystem object store is
rooted in a private directory selected by the operator.  The lab bootstrap
creates or refreshes a dedicated test tenant, account, License, and hardware
binding by calling the existing access-control services.

A small ASGI fault boundary wraps the seed app.  It applies named, temporary
rules only after a loopback-only control request with a randomly generated
local control token.  Rules are scoped by HTTP method and path prefix, expire
automatically, and produce a redacted local audit event.  The wrapper supports
unavailable/503, response latency, response throttling, execute-then-drop
completion responses, repeated completion acknowledgements, delayed
acknowledgements, and a supervisor-requested application restart.  It never
forwards a control request to the seed app and is rejected if configured to
bind beyond loopback.

## Operator boundary

`scripts/local_controlled_integration_lab.py` is the operator entrypoint.  It
creates a private runtime tree below the local application-data directory by
default and rejects repository, project-context, OneDrive, and reparse-point
roots.  That tree holds the generated test CA/server certificate, token and
database settings, object store, audit stream, and transient client delivery.
The repository contains only the command, typed configuration schema, scenario
definitions, and redacted evidence.

The command has three explicit phases:

1. `preflight` verifies loopback, a PostgreSQL 15+ administration DSN, required
   local directories, and TLS capability before changing service state.
2. `bootstrap` creates the local database roles/databases, runs the committed
   migrations, provisions the test tenant/account/License/hardware binding,
   and writes credentials only in the private runtime tree.
3. `serve` runs a local TLS Uvicorn process under a supervisor that restarts
   only the local child when a controlled restart is requested.

The initial implementation uses an explicit PostgreSQL administration DSN
rather than installing a database server.  This keeps operating-system package
installation and database ownership outside repository code while making the
missing host prerequisite actionable and testable.

## Scenario and evidence model

Each requested scenario has a generated correlation ID, a finite expiry, rule
identifier, matching method/path, and outcome counts.  The local audit log
records hashes of correlation IDs and paths plus state transitions; it never
records tokens, passwords, activation codes, License documents, raw payloads,
or database DSNs.  The acceptance runner uses a real HTTP client against TLS
and asserts all of the following for each scenario:

- the client-side queue/retry result;
- the final persisted session status (`INGESTED` or `VALID` as applicable);
- the exact server-side idempotent mutation count;
- a redacted fault audit event.

The runner covers temporary 503, latency/throttle, supervisor restart,
execute-then-drop/repeat, and acknowledgement delay/reordering.  Its inputs
are generated test data only.  It refuses a non-loopback URL, a production
credential environment variable, or a runtime root that fails the isolation
checks.

## Failure handling and tests

The fault boundary defaults to pass-through and validates every rule before it
becomes active.  A bad token, expired rule, non-loopback host, or unsafe
runtime root produces a safe local error with no partial rule activation.
Restart requests are acknowledged in the audit log before the child exits; the
supervisor preserves the PostgreSQL and filesystem roots and emits its recovery
event after readiness returns.

Unit tests use the real ASGI wrapper around the existing in-memory integration
composition to prove each fault's wire behavior and audit redaction.  CLI tests
use temporary private roots and fake administrative operations to prove
preflight and bootstrap safety.  A live acceptance test is opt-in and requires
the local PostgreSQL service; it uses the generated runtime materials and is
the only test that asserts persistence across a real child-process restart.

## Documentation and non-goals

`cloud/api/README.md`, `docs/modules/06-cloud-ingestion.md`, and
`docs/通信接口设计文档.md` will document installation prerequisites, the private
runtime boundary, commands, scenarios, and evidence limitations.  This lab is
not a production deployment, does not connect to the remote integration
endpoint, does not accept production credentials/data, and does not replace
the RAY-428 real-device and remote normal-upload evidence already collected.
