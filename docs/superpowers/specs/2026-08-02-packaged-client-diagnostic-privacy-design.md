# Packaged Client Safe Logs and Diagnostic Export Design

**Date:** 2026-08-02

**Linear scope:** RAY-96

**Status:** Approved design awaiting written-spec review

## 1. Purpose

The packaged institution client needs useful installation, authentication, upgrade, and support evidence without allowing passwords, one-time activation codes, refresh tokens, License signing material, patient identity, request/response bodies, or arbitrary exception text into client logs or diagnostic packages.

This design covers the packaged-client software boundary on the current macOS development machine. It does not claim Windows installer behavior, dual-platform smoke testing, physical hardware acceptance, deployed support-key operations, non-technical operator acceptance, production authorization, or clinical validation.

## 2. Decision

Use typed, allowlisted client events as the only persistent support log and the only event input to a public-key-encrypted diagnostic package.

Do not collect ordinary text logs and redact them afterward. Redaction cannot reliably identify arbitrary names, token formats, or signing material. Do not recursively scan application data, environment variables, Keychain, SQLite, customer reports, or existing log directories when creating a diagnostic package.

## 3. Components and ownership

### 3.1 Safe client event contract

A new packaged-client support module owns an immutable `SafeClientEvent` contract. It accepts only:

- event UUID and UTC timestamp;
- a closed category enum: application, installation, authentication, upgrade, or diagnostic export;
- a closed event-name enum;
- a closed outcome enum;
- a stable error code matching the existing public-code format, or `null`;
- application, protocol, data-mode, and configuration version identifiers;
- opaque `ClientInstallation` UUID;
- bounded numeric counters such as attempt number, pending event count, and duration;
- schema version and previous event digest needed for integrity chaining.

The contract has no general-purpose message, context dictionary, exception, path, account, tenant display name, subject, report body, token, activation code, signed License, or cryptographic-key field. Unknown fields fail validation.

### 3.2 Safe event writer

`SafeClientEventWriter` writes canonical JSONL under the platform-owned application data directory, not the installation directory. Files and directories use private permissions (`0600` files and `0700` directories where supported).

The writer:

- accepts only a validated `SafeClientEvent`;
- computes a SHA-256 chain over canonical event bytes;
- appends and flushes one complete event at a time under a process lock;
- rotates at 2 MiB and retains at most three generations;
- recovers by discarding only an incomplete final line;
- never accepts `str(exception)`, an HTTP body, headers, request data, environment values, or arbitrary dictionaries.

Logging failure is non-fatal to activation, login, local screening, safe exit, or upgrade rollback. The caller receives only a boolean recording result; no sensitive fallback log is created.

### 3.3 Packaged-client integration

The formal packaged entry constructs one writer after the application data directory is available. Typed recorder calls are added at these boundaries:

- application start and normal exit;
- activation/login/refresh success or safe rejection;
- upgrade compatibility check, migration start/result, rollback result;
- diagnostic export start/result.

Recorders receive safe outcomes from the orchestration layer. Raw password, confirmation, activation code, refresh token, access token, signed License, server response, and caught exception objects remain outside the recorder API.

The P-11 support action calls the diagnostic exporter through an injected port. If the support public key is unavailable or invalid, the client returns a stable customer-safe error and creates no plaintext or partially encrypted artifact.

### 3.4 Diagnostic snapshot and archive

The exporter builds a deterministic ZIP in memory containing only:

- `manifest.json`: diagnostic schema, creation time, safe version matrix, platform family, opaque installation UUID, event count, and `contains_customer_data=false`;
- `safe-events.jsonl`: validated events selected from the bounded safe-event store;
- `integrity.json`: entry SHA-256 values and the final event-chain digest.

The exporter does not accept arbitrary attachment paths. It does not query customer/subject tables, reports, raw sessions, encrypted segments, Keychain, environment variables, ordinary log directories, or the local access-session store.

Before encryption, every event is parsed again through the strict contract. A malformed, extra-field, or digest-invalid event stops export with a stable safe error; it is never copied into the package.

## 4. Encryption format

The build manifest selects a pinned support-recipient X25519 public key and non-secret key identifier from a read-only packaged resource. There is no runtime environment-variable or network fallback for this key. The corresponding private key is never present in the client, installer, repository evidence, or License signing configuration.

For each export:

1. Generate a fresh ephemeral X25519 key pair.
2. Derive a 256-bit content key with X25519 plus HKDF-SHA-256 using the format and recipient key IDs as context.
3. Encrypt the in-memory ZIP with AES-256-GCM and a random 96-bit nonce.
4. Write a versioned `ffpdiag/1` envelope containing only the recipient key ID, ephemeral public key, nonce, ciphertext, and ciphertext SHA-256.
5. Publish atomically as a mode-`0600` `.ffpdiag` file; no plaintext temporary file is written.

Encryption failure, invalid public key, interrupted write, or destination error deletes only the temporary encrypted output. Existing diagnostics and application data are not modified.

## 5. Privacy invariants

The implementation must maintain all of these invariants:

1. No production logging API accepts free-form messages or exception objects.
2. No auth or License request/response model is serialised into a support event.
3. Passwords, password confirmations, activation codes, refresh/access tokens, signed License documents, License private/public signing material, patient names, institution record numbers, contact details, and report content cannot be represented by the event contract.
4. Diagnostic export reads only the safe-event store and explicit safe version/platform metadata.
5. Plaintext archive bytes exist in memory only for the duration of encryption.
6. Customer-visible failures contain stable error codes and actions, not low-level exception text.
7. Evidence and tests use synthetic canaries only; no real credential, patient, institution, key, or local database enters Git or Linear.

## 6. Verification strategy

Implementation will use test-driven development. The evidence matrix must include:

- contract tests rejecting unknown keys and every credential/identity-shaped field;
- actual activation, login, refresh, upgrade, and export failure flows using distinct synthetic canaries for password, one-time code, refresh token, access token, signed License, License private key, patient name, institution record number, and contact information;
- safe-log inspection proving none of the exact canaries or forbidden field names appears;
- diagnostic export with a test X25519 private key, followed by decryption and ZIP inspection proving the same absence and the exact fixed file list;
- malformed/extra-field/digest-broken event rejection before export;
- missing/invalid support public key and interrupted-output tests proving no plaintext or partial final artifact remains;
- file and directory permission tests;
- rotation/restart recovery tests;
- regression tests showing logging/export failure does not block login, local screening, safe exit, or upgrade rollback;
- packaged-entry and P-11 adapter composition tests;
- focused JUnit, full repository regression, Ruff, Mypy, compileall, and `git diff --check`.

Canary tests prove the implemented data flow and exact artifact contents. Static source searches may supplement evidence but cannot independently close the Linear criterion.

## 7. Linear completion rule

The RAY-96 privacy item may be checked only after:

- the formal packaged client uses the safe writer and encrypted exporter;
- the canary matrix, decrypted-package inspection, packaged composition, and full regression pass;
- sanitized evidence with commands, hashes, results, source commit, and explicit platform/deployment limitations is stored under `docs/evidence/linear/RAY-96/`;
- live RAY-96 is reread, only the exact privacy checkbox is updated, a bounded evidence comment is posted, and the issue is reread again.

RAY-96 must remain `In Review` because Windows installer/CH340, real activation with registered hardware, replacement-computer behavior, dual-platform smoke testing, and non-technical operator acceptance remain separate criteria.
