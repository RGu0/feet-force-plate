# Mobile API contracts

`openapi.json` and `vectors.json` are deterministic public artifacts of the
existing FeetForcePlate API. They contain no deployment endpoints or real keys.
Generate through the governed `build` action; the test gate detects drift.
Consume the JSON files at a pinned Git commit/tag and retain their SHA-256 with
the client build. Versioned source distributions include these tracked files;
CI also archives them with commit identity. This export does not claim that
gait-insole routes, hardware registration or institutional access rules have
been deployed.

The server wraps success in `data` + `meta`; failures use `error` + `meta`.
Foundation's top-level `ErrorEnvelope` is a different mechanism. Follow both
`retryable` and `action`; equal error codes can have different required actions.
Keep `X-Correlation-ID` a UUID (the business gateway rejects non-UUID values).
Idempotent session/segment creation returns 201 initially and 200 on replay;
reuse the exact idempotency key and request, and treat changed payload as conflict.

For Dart, decode the JSON fixtures directly; do not reconstruct the signed bytes
using default `jsonEncode` ordering. Decode `canonical_hex` and verify the
Ed25519 signature against `public_key_base64`. The example key is synthetic and
untrusted for production. Test tampered document/signature and unknown key id.
Metadata uses unpadded base64url of UTF-8 canonical JSON (sorted object keys,
compact separators, Unicode unescaped, non-finite numbers rejected); array
order is preserved. Binary payload digest is lowercase full SHA-256 over the
bytes before any transport encoding. `payload_base64` is only a fixture carrier,
not the HTTP body; PUT the decoded bytes as `application/octet-stream` and send
`X-Content-SHA256`, `X-Schema-Version`, `X-Segment-Metadata` from the fixture.

RAY-656 adds institutional multi-terminal routes under `/v1/access/terminal-*`
and `/v1/access/terminals`, plus the `terminal` vector section. Activation takes
account + password + terminal name + `client_installation_id` + platform, with no
activation code. Each operation's `x-ffp-error-codes` lists its distinct codes:
revoked, seat limit, refresh replayed, refresh expired, and so on. Branch on
`error.code`; never infer revocation from a bare 401. The signed
`terminal-license/1` document carries `seats` and verifies with the same fixture
key procedure as `license/2`.

Refresh rotation: a rotated token replayed within `replay_grace_seconds` (30,
inclusive) returns the identical successor refresh token and a new access token.
A later replay, or a replay after the successor was used, revokes the whole
family (`E-TRM-401-REFRESH-REPLAYED`). Persist the newest refresh token before
using it, and retry a lost refresh response with the previous token inside the
window. Every `refresh_rotation` and `seats` scenario is replayed against the
server in `cloud/tests/test_terminal_access.py`.

Dart consumption: as of 2026-10-07, RAY-643 (Done) recorded native Dart
consumption of these fixtures in gait-insole-flutter (PR 7). That evidence
predates the RAY-656 `terminal` section; client alignment for it is tracked by
RAY-657. iOS/Android real TLS evidence remains a separate acceptance step, and
no mobile pass is implied by Python export tests.
