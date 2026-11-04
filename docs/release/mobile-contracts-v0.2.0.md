# Mobile API contracts v0.2.0

## Scope and source

- Linear: RAY-666, scope `contract-release-v0-2-0`, requirement revision `R1`
- Release tag: `v0.2.0` (the `pyproject.toml` package version and `APP_VERSION`)
- Contract source commit: `f4e3b2bf98341d85160a02011bf4a805c5011887` (RAY-656 PR #67,
  merged as `5f923e7`), unchanged at tag time
- Previous release: `v0.1.0` (`docs/release/mobile-contracts-v0.1.0.md`)
- Release assets are attached by `.github/workflows/mobile-contract-release.yml`
  after it re-runs `cloud/tests/test_mobile_contract_export.py` at the tagged commit.

## Assets

| File | SHA-256 |
| --- | --- |
| `openapi.json` | `705adf31d0b46ef9dace98c66711d5aceaf4a30cbcfef13246a77b42895abf96` |
| `vectors.json` | `b65c822630e0d5319c6a7467c5385f905067b69941c06b51f5ac4f0c2508c068` |

## Changes since v0.1.0

- New institutional multi-terminal routes (RAY-656):
  `POST /v1/access/terminal-activate`, `POST /v1/access/terminal-refresh`,
  `GET /v1/access/terminals`, `PATCH /v1/access/terminals/{client_installation_id}`,
  `POST /v1/access/terminals/{client_installation_id}/revoke`.
- New `terminal` vector section: `activation_request`, `refresh_request`,
  `refresh_rotation`, `seats`, `errors`, and the signed `terminal-license/1` sample.
- Unchanged: OpenAPI `3.1.0`, `info.version` `1.0.0`, `schema_version`
  `mobile-contract-vectors/1`, and every v0.1.0 route and vector section.

## Consumption

Pin the `v0.2.0` tag or the asset SHA-256 values above and keep those values with
the client build. Read `cloud/contracts/mobile/README.md` for the envelope, replay,
segment-header, License, and terminal refresh-rotation rules.

## Boundary

These are offline contracts for routes that already exist. They contain no deployment
endpoints, real keys, or personal data. Fixture keys are synthetic and must not be
trusted. Client alignment for the `terminal` section is tracked by RAY-657, and
iOS/Android real TLS remains a separate acceptance step.
