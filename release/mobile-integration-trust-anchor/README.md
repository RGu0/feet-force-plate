# Mobile integration trust anchor (RAY-812)

Public material for the gait-insole-flutter **integration** build to verify
`terminal-license/1` documents signed by the Alibaba Cloud integration endpoint.
Without it a release build trusts no License key and reports `E-ACC-4017`.

| File | Purpose |
| --- | --- |
| `license-public.key` | 32-byte raw Ed25519 License verification key |
| `cloud-default.json` | endpoint `https://39.105.216.113:7443`, `license_key_id` `license/1` |
| `cloud-ca.pem` | private root CA (`FeetForcePlate Private Root CA`, expires 2036-08-01) |
| `SHA256SUMS` | digests of the three files above |

Digests (verify before bundling):

- `license-public.key` `40b50ea2f5ac5287c8716652722d6b8129f6a342888ce6f554953cc879abe0d7`
- `cloud-ca.pem` `402af560c1b81af6cb7cce7c6bcbd06de3f09ad2e35fef4a7b4a8c966df9b5ac`
- CA SHA-256 certificate fingerprint
  `9D:97:78:18:6A:ED:F2:3C:06:3E:E6:40:F8:46:63:FA:B5:18:C4:DA:0C:0F:4F:82:4D:47:19:5B:B7:BC:6E:44`

## Verified against the live endpoint

A real `terminal-license/1` issued by the integration endpoint on 2026-10-22
(`key_id=license/1`) verifies with this key
(`license.signature_verified=true`, RAY-785 route smoke).

## This is not a production trust anchor

The key is the single integration signing key on the Aliyun host. It must not be
shipped in a customer or production build. Production signing-key generation,
rotation and publication are tracked under RAY-517. If the host key is
regenerated, this bundle is stale and must be re-exported.

The directory contains public material only: no private key, token or credential.
