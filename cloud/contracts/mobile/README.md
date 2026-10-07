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

Dart consumption and iOS/Android real TLS evidence remain separate acceptance
steps. Current `gait-insole-flutter/packages/cloud_client` is a placeholder and
has not yet run these fixtures. No mobile pass is implied by Python export tests.
