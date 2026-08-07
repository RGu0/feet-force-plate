# FeetForcePlate packaging contract

This directory defines the repeatable packaging inputs for the institution client. It is a build contract, not evidence that a signed installer has been produced.

## Build inputs

- `FeetForcePlate.spec` describes the PyInstaller application bundle.
- `build-config.json` records target-platform, signing, driver-readiness, persistent-data, and controlled-upgrade requirements.
- Repository `main.py` is the frozen application entry point; it routes the
  no-argument package to the formal institution application and keeps replay
  and design-demo modes explicit.

Local macOS development build (the wrapper keeps the uv environment outside
OneDrive):

```text
./scripts/local-env.sh uv run --extra dev --extra build python -m PyInstaller \
  --noconfirm --clean \
  --distpath /private/tmp/feetforceplate-macos/dist \
  --workpath /private/tmp/feetforceplate-macos/build \
  client/app/packaging/FeetForcePlate.spec
```

The spec produces an onedir `.app` bundle, reads the application version from
`pyproject.toml`, and relies on PyInstaller's import-driven PySide6 hooks rather
than bundling the complete Qt development toolchain.

Signing certificates, notarization credentials, activation credentials, and other secrets must be supplied only by the protected CI keychain or secret store. They must never be embedded in the repository or package metadata.

## Optional diagnostic-support recipient

Build tooling may set `FEETFORCEPLATE_SUPPORT_RECIPIENT_FILE` to one
non-group/world-writable JSON resource containing the support-owned X25519
**public** key, its technical key ID, and schema
`feetforceplate-support-recipient/1`. The spec stages the resource as the fixed
packaged name `support-recipient.json` (Unix mode `0644`, which the loader
accepts) before collection; it does not place its source path or environment
value in application metadata.
The corresponding private key remains support-owned and must never be
packaged, committed, or provided to the application.

Omitting the resource, or a malformed/group-or-world-writable resource, does not stop the
packaged application from starting. It disables P-11 diagnostic export
fail-closed with customer-safe error `E-SUP-001`. Tests generate temporary
keys/resources only; they do not establish deployed key custody, a Windows
package, or target-OS packaging acceptance.

## Packaged cloud default

To bind a package to a cloud environment by default, set
`FEETFORCEPLATE_CLOUD_DEFAULT_DIRECTORY` to a directory containing exactly
these public files:

- `cloud-default.json`: endpoint, channel, and License key ID;
- `cloud-ca.pem`: the pinned CA certificate/chain; and
- `license-public.key`: the 32-byte Ed25519 License verification key.

The spec validates these files then stages fixed package resource names; it
never stores the build-input path. Process environment variables remain an
explicit override for development and recovery. Do not put a private License
key, database DSN, API token, or any activation credential in this directory.
The current 7443 self-signed endpoint is an `integration` bundle only; a
user-facing distribution requires an approved HTTPS endpoint on the standard
port and its production trust material.

## Platform requirements

- Windows: produce a signed outer installer; check CH340 driver readiness before device use and present a plain-language remediation path. Do not silently install a driver without operator or administrator confirmation.
- macOS pilot: sign the app bundle and notarize packages distributed outside the development team.
- Keep the installation directory separate from the persistent database, encrypted raw-data segments, logs, and cached configuration. Uninstall and rollback must preserve those persistent directories unless an authorized operator explicitly requests data removal.

## Controlled upgrade sequence

1. Verify package signature, digest, minimum supported version, and data-schema compatibility.
2. Refuse activation while acquisition or report generation is active.
3. Stage the candidate package and create a database snapshot.
4. Run the migration, activate the candidate, and retain the previous app version.
5. If migration or activation fails, restore both the previous app version and database snapshot.

A local arm64 macOS development bundle can be built and ad-hoc signed for
developer smoke tests. Developer ID signing, hardened runtime, notarization,
Gatekeeper acceptance, universal2 output, install/upgrade/uninstall and
data-retention smoke tests remain external-pilot or target-OS acceptance work.
Windows signing/builds, CH340 installation, real activation, and printer smoke
tests also remain target-OS/manual acceptance work.
