# RAY-81 Evidence - DO-P4864 协议解析与接收完整性审计

- URL: https://linear.app/ray-app/issue/RAY-81/do-p4864-协议解析与接收完整性审计
- Captured at: 2026-07-20T08:57:11Z
- Snapshot: In Progress; P1：可靠采集; High
- Related: blocked by RAY-78

## Acceptance snapshot

- [x] byte/random chunks, partial/sticky/continuous frames
- [x] header, length, function, CheckSum, and tail validation
- [x] next-header resynchronization and bounded buffer
- [x] valid/checksum/resync/byte/interval audit statistics
- [x] little-endian uint16 decode with low-12-bit mask
- [x] synthetic noise injection and deterministic fuzz tests
- [ ] physical serial golden fixture

## Implementation and decisions

Test-first implementation uses an explicit protocol profile. Synthetic tests may select length order and CheckSum coverage only when labeled unverified; the default parser rejects such profiles. A capture-verified profile requires a 64-character fixture SHA-256.

Current files:

- `client/device/__init__.py`
- `client/device/protocol.py`
- `tests/__init__.py`
- `tests/device/__init__.py`
- `tests/device/test_protocol.py`
- `tests/fixtures/device/README.md`

## Verification

Command:

```text
/Users/ruiguo/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest tests/device/test_protocol.py
```

TDD evidence:

- RED: missing parser module failed as an assertion.
- GREEN: minimal parser surface passed.
- RED: missing explicit profile/evidence gate failed.
- GREEN: synthetic profiles are rejected by default.
- RED: missing capture-verified digest constructor failed.
- GREEN: invalid fixture SHA-256 is rejected.
- RED/GREEN: single-byte incremental feed now emits immutable 48x64 uint16 matrices with low-12-bit masking, host clocks, source_index, and an unverified-profile quality flag.
- RED/GREEN: random chunking and sticky frames preserve order and produce bounded interval aggregates.
- RED/GREEN: leading noise and a bad CheckSum resynchronize at the next header and increment audit counters.
- RED/GREEN: sustained noise respects the configured retained-buffer hard limit.
- RED/GREEN: bad length, function, and tail fields are counted separately.
- RED/GREEN: direct dataclass construction cannot bypass the fixture-digest gate.
- Acceptance coverage: a profile controls length byte order and CheckSum slice; deterministic random noise/fuzz recovers 40 inserted frames.
- Fresh focused result: 11 tests passed in 0.029 s with warnings treated as errors.
- Fresh owned discovery result: 11 tests passed in 0.029 s with warnings treated as errors.
- `compileall -q client/device tests/device`: exit 0.

The broader `client/tests` discovery is not a RAY-81 pass signal: it currently
has 22 discovered tests with 3 import errors in other task-owned code (missing
`PySide6` for RAY-101 tests and missing `TenantBoundaryError` for RAY-92). No
files in those scopes were changed by this issue.

## Boundary, failures, and limits

Automated tests use NumPy and the actual parser, but synthetic wire profiles do
not prove the physical device's length-byte order or CheckSum coverage. No raw
serial capture exists. The manual and DAOONE exports cannot close the
golden-fixture acceptance item, so this issue must remain short of Done.

## Commit

Implementation and initial evidence: `7468e749ecfc4d61075fcef6573b855046973b91`.
