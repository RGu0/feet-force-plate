# DO-P4864 protocol fixtures

No physical serial golden fixture is present yet.

The DAOONE `.csv` and `.txt` files under `refs/` are decoded 48x64 matrix
exports, not wire captures: they do not contain the header, transmitted length
bytes, function code, CheckSum byte, or tail. They therefore cannot establish
the length-field byte order or CheckSum coverage range.

Tests may construct bytes with a profile whose evidence class is `SYNTHETIC`.
Such a profile is accepted only when the caller explicitly opts into unverified
data, and emitted frames carry `PROTOCOL_PROFILE_UNVERIFIED`.

A future physical fixture must be accompanied by metadata containing at least:

- capture time and tool/version;
- device/receiver identity without personal data;
- serial settings;
- raw, unmodified bytes and SHA-256;
- observed transmitted length bytes;
- experimentally verified CheckSum start/end offsets;
- protocol profile version and reviewer.
