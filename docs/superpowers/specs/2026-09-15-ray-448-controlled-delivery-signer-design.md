# RAY-448 controlled delivery signer design

**Date:** 2026-09-15
**Scope:** `controlled-delivery-signer`
**Requirement revision:** R5

## Decision

RAY-448 adds a source-controlled program for an offline protected signing
machine. The program is not a key store and cannot discover keys. Its operator
passes an explicit local signer-policy path; that policy names one raw 32-byte
Ed25519 private-key file held outside the repository, worktree and shared
`project-context`. Before issuing, the signer derives that private key's public
key and requires an exact match with the fixed RAY-448 verifier trust anchor in
`client.cloud.windows_bundle`.

The program does not provision that policy, its private key, or an audit-log
location. Any path shown in release instructions, including
`D:\FeetForcePlate\protected-signer\policy.json`, is an operator-provisioned
example rather than an existing convention. The protected-signer administrator
must create those local-only materials outside synchronized storage before
passing the actual policy path to the program.

The policy file is local-only and is never copied to delivery evidence. It
contains `source`, `approved_by`, `private_key_file`, `audit_log_file` and a
maximum request lifetime. The key bytes, policy path and key path are never
printed or written to audit records. The offline machine and its protected
operator account form the authorization boundary; callers cannot choose a
trust anchor or sign with a different key.

## Request and output

A request is canonical JSON with a unique strict schema. It must identify an
already approved human, request time, expiry time and full target commit. The
command rejects unapproved requests, a different approver, malformed UTC
values, expiry in the past, a lifetime greater than policy, or a dirty project
worktree whose HEAD differs from the requested commit. It derives endpoint,
channel, license key ID and all three public-default resource digests directly
from the supplied source directory, so none of those release inputs are
caller-provided claims.

On success it creates a new output directory containing exactly:

- `approval.json`, canonical UTF-8 approval payload accepted by the existing
  public RAY-448 verifier;
- `approval.sig`, its Base64 detached Ed25519 signature.

The resulting pair can then be copied by the established `prepare` command
into the five-file delivery tree. The command never overwrites a previous
output directory.

## Audit and recovery

Every accept or reject appends a newline-delimited public audit record at the
protected configured audit path. Records contain only operation result,
request digest, timestamp, target commit when safely parsed, approver and a
sanitized reason. `audit` filters by target commit without reading a private
key. If the signer configuration or key is unavailable, or its derived public
key does not match the built-in anchor, the command fails before writing an
approval pair and records the refusal whenever the audit location is available.

A future trust-anchor rotation is a separate RAY-448 scope: update the fixed
client key first, then provision an offline policy/key matching it, and
reissue approvals. Revoking a signer means removing its policy/key access;
the client still accepts only the currently compiled anchor.

## Validation

Tests use generated temporary keys only. They cover accepted output passing the
existing verifier, request/identity/expiry rejection, source commit and digest
binding, wrong-key failure, signer-unavailable fail-closed behavior, queryable
redacted audit records, and CLI refusal to use another checkout. The actual
private signing key remains outside the repository and is never inspected by
tests or commands in this scope.
