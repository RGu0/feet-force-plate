# FeetForcePlate packaging contract

This directory defines the repeatable packaging inputs for the institution client. It is a build contract, not evidence that a signed installer has been produced.

## Build inputs

- `FeetForcePlate.spec` describes the PyInstaller application bundle.
- `build-config.json` records target-platform, signing, driver-readiness, persistent-data, and controlled-upgrade requirements.
- `client/app/packaged_entry.py` is the package smoke-test entry point.

Signing certificates, notarization credentials, activation credentials, and other secrets must be supplied only by the protected CI keychain or secret store. They must never be embedded in the repository or package metadata.

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

Real Windows and macOS builds, signing/notarization, CH340 installation, upgrade/uninstall, data-retention, activation, and printer smoke tests remain target-OS/manual acceptance work.
