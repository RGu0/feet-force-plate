# Integration Public Bundle Design

## Purpose

Provide a root-run server helper that creates the exact public build input for
the RAY-99 integration client. Its fixed destination is
`/srv/feetforceplate/acceptance-public/ray-99-integration/`.

This is an integration-only artifact. It does not deploy an application,
restart a service, create a License, or perform the client upload acceptance.

## Interface

Create `deploy/aliyun/seed/build-integration-public-bundle.sh`. The operator
runs it as root with four explicit public inputs:

```text
sudo ./deploy/aliyun/seed/build-integration-public-bundle.sh \
  --api-base-url https://integration.example:7443 \
  --ca-cert /approved/public/cloud-ca.pem \
  --license-public-key /approved/public/license-public.key \
  --license-key-id integration-license/1
```

The script accepts one optional `--replace` flag. Without it, an existing
destination is a hard error. With it, the script retains the prior public
bundle as a timestamped sibling directory; it never deletes prior material.
The command prints only a success summary, destination, SHA-256 digests, and
the public endpoint/key ID. It never prints file contents or private runtime
configuration.

## Output Contract

The published bundle directory contains exactly these regular files, each mode
`0644`, under a mode-`0755` root-owned directory:

1. `cloud-default.json`, encoded UTF-8 and containing exactly the six fields
   accepted by `client.cloud.packaged_defaults`:
   `schema_version`, `channel`, `api_base_url`, `license_key_id`,
   `ca_bundle_resource`, and `license_public_key_resource`.
2. `cloud-ca.pem`, copied from the explicit CA input.
3. `license-public.key`, copied from the explicit Ed25519 public-key input.

The JSON has schema version `feetforceplate-client-cloud-default/1`, channel
`integration`, the supplied HTTPS API URL with explicit port `7443`, and the
fixed resource names `cloud-ca.pem` and `license-public.key`.

## Safety and Failure Behavior

The shell wrapper uses `set -euo pipefail`, `umask 077`, requires effective
UID 0, accepts no positional arguments, and fails closed on unknown or missing
options. It does not source `/etc/feetforceplate/seed.env`, inspect systemd
units, read DSNs, private License keys, API tokens, or activation credentials.

Both supplied source files must be ordinary readable files rather than
symlinks. A small embedded Python validator constructs and validates the JSON
with `urllib.parse`, checks that the public key is either 32 raw bytes or
base64 decoding to 32 bytes, and requires the CA input to be nonempty. It
creates the output in a same-filesystem staging directory, validates the three
staged fixed-name files, then publishes it. An existing output is untouched on
any validation error.

For a replacement, the current directory is moved to a timestamped sibling
before the validated staging directory is moved into the fixed destination.
The prior public bundle is retained for recovery; automated cleanup is
explicitly out of scope.

## Verification

Add shell-level tests that run the script in a temporary root with stubbed
`install`-compatible filesystem paths. Tests cover a valid bundle, refusal to
overwrite without `--replace`, rejection of a non-7443/non-HTTPS URL,
rejection of an invalid public-key length, rejection of symlink input, and the
guarantee that a failed replacement leaves the prior bundle unchanged. Validate
the resulting files with `client.cloud.packaged_defaults.load_packaged_cloud_defaults`.

The scope's governed test, lint, and build commands remain required before a
PR is offered. The real remote execution remains an operator-run acceptance
step and must be recorded separately without credentials.
