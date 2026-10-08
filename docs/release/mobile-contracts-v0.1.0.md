# Mobile API contracts v0.1.0

## Scope and source

- Linear: RAY-641, scope `contract-release`, requirement revision `R1`
- Release tag: `v0.1.0` (the `pyproject.toml` package version)
- Contract source commit: `010e5a6c3c3d1bba455b29208c003b49a77f163c` (PR #64), unchanged at tag time
- Release assets are attached by `.github/workflows/mobile-contract-release.yml`
  after it re-runs `cloud/tests/test_mobile_contract_export.py` at the tagged commit.

## Assets

| File | SHA-256 |
| --- | --- |
| `openapi.json` | `65487192e36d7e183f354549b4e9ddbc421ddf2f785d5178edab69fe6d425fe3` |
| `vectors.json` | `46a8152c1f13d184379e60558b883113f9d4f09cbb5e8d2f1a865ffde6501043` |

- `openapi.json`: OpenAPI `3.1.0`, `info.version` `1.0.0`, covering the existing
  `/v1/access/*`, `/v1/subjects*`, `/v1/consents*`, `/v1/sessions*` (including
  segments, complete, and status) routes.
- `vectors.json`: `schema_version` `mobile-contract-vectors/1`, with sections
  `success`, `errors`, `session_replay`, `segment`, and `license`.

## Consumption

Pin the `v0.1.0` tag or the asset SHA-256 values above and keep those values with
the client build. Business success uses `data` + `meta`; failures use
`error` + `meta`. Read `cloud/contracts/mobile/README.md` for the replay,
segment-header, and License verification rules.

## Boundary

These are offline contracts for routes that already exist. They contain no deployment
endpoints, real keys, or personal data. The License key in them is synthetic and must
not be trusted. They do not show that gait-insole routes, hardware registration, or
iOS/Android real-TLS behaviour are deployed. Dart consumption was verified separately
under RAY-643.
