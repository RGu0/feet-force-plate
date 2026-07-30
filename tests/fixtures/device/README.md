# DO-P4864 protocol fixtures

The capture-backed `observed_compact_8bit` runtime profile is the physical
serial baseline for frame-boundary integrity. Its raw capture remains local-only
and is referenced by SHA-256 in the protocol profile.

`dop4864_reference_protocol_v1/` is intentionally different: it contains a
de-identified, derived 48×64 matrix replay from a physical four-pose run. It
is the canonical software/UI replay input, not a raw serial golden fixture.
Its README and metadata define its integrity hash and usage boundary.

The DAOONE `.csv` and `.txt` files under `refs/` are decoded 48x64 matrix
exports, not wire captures: they do not contain the header, transmitted length
bytes, function code, CheckSum byte, or tail. They therefore cannot establish
the length-field byte order or CheckSum coverage range.

Tests may construct bytes with a profile whose evidence class is `SYNTHETIC`.
Such a profile is accepted only when the caller explicitly opts into unverified
test data, and emitted frames carry `PROTOCOL_PROFILE_UNVERIFIED`.

Additional captures should be accompanied by metadata containing at least:

- capture time and tool/version;
- device/receiver identity without personal data;
- serial settings;
- raw, unmodified bytes and SHA-256;
- observed transmitted length bytes;
- observed CheckSum candidates and mismatch count;
- protocol profile version and reviewer.
