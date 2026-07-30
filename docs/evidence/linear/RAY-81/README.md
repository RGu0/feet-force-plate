# RAY-81 Evidence - DO-P4864 协议解析与接收完整性审计

- URL: https://linear.app/ray-app/issue/RAY-81/do-p4864-协议解析与接收完整性审计
- Captured at: 2026-07-30T04:00:00Z
- Snapshot: In Review; P0：硬件基线; High
- Protocol boundary: observed 3,079-byte compact `uint8` stream only

## Acceptance snapshot

- [x] Supports byte-wise, random-chunked, partial, sticky, and consecutive frames.
- [x] Hard-validates header, function code, and tail; length and CheckSum are audit-only for the observed profile.
- [x] Records length/CheckSum observations and mismatches without dropping an otherwise structural frame.
- [x] Resynchronizes to the next header without clearing the full buffer, with a bounded retained buffer.
- [x] Audits received bytes, valid/invalid frames, length and CheckSum observations/mismatches, resynchronizations, discarded bytes, peak buffer, and host frame intervals.
- [x] Uses a deterministic synthetic golden wire fixture, fault injection, and seeded fuzz recovery.
- [x] Carries `PROTOCOL_PROFILE_UNVERIFIED`, `COMPACT_8BIT_PAYLOAD_UNVERIFIED`, and the relevant non-enforcement/mismatch quality flags before vendor confirmation.
- [ ] Vendor-confirmed serial golden fixture that establishes raw-value semantics, length meaning, and CheckSum formula.

## Implementation and decisions

`client/device/protocol.py` is the only byte-stream decoder. Its default
observed profile accepts a structural 3,079-byte frame:

```text
FF AA | 0C 07 candidate length | 01 | 3,072-byte raw content | CheckSum candidate | FA
uint8(frame[5:3077]).reshape((48, 64), order="F")
```

The historical 6,151-byte/12-bit interface is not exposed by this runtime.
The frame header, function code, and tail are structural rejection criteria.
For the observed profile, the `0x0C07` length candidate and CheckSum candidate
are counted as observations only. A mismatch marks the decoded frame but does
not discard it. A capture-verified profile may require those rules only after a
fixture SHA-256 and supplier evidence establish their semantics.

Parser matrices and transport statistics remain hardware-layer data. They are
not a direct algorithm input and, because the device exposes neither a sequence
number nor a clock, they support only host-side receive-quality observation.

## Verification

Executed with the repository wrapper on macOS / Python 3.11.15:

```text
QT_QPA_PLATFORM=offscreen ./scripts/local-env.sh python -m pytest \
  --junitxml=docs/evidence/linear/RAY-81/pytest-parser-audit-regression.xml \
  tests/device/test_protocol.py tests/device/test_simulator.py \
  tests/device/test_acquisition.py
# 36 passed

QT_QPA_PLATFORM=offscreen ./scripts/local-env.sh ruff check \
  client/device/protocol.py tests/device/test_protocol.py
# All checks passed

QT_QPA_PLATFORM=offscreen ./scripts/local-env.sh mypy
# Success: no issues found in 10 source files
```

The regression includes single-byte delivery, arbitrary chunk sizes, sticky
frames, leading noise, corrupt candidates, next-header recovery, bounded
buffers, simulator faults, deterministic fuzz recovery of 40 frames, and the
new audit-only length-candidate mismatch case.

## Historical structural capture

A read-only 60-second serial capture was previously recorded locally in commit
`bb1b1fe`: 3,835,531 raw bytes (local-only SHA-256
`1d91bdd071f667481d76b4eb54a75f675a3a8b177505e0f114657402c90d9cc9`),
1,245 decoded frames, zero invalid frames, zero resynchronizations, and 1,245
candidate CheckSum mismatches. It supports this host-observed structural profile
only; raw bytes are intentionally not committed.

## Boundary and remaining review

RAY-81 remains **In Review**. Automated fixture results and the structural
capture do not prove CheckSum coverage, length-field semantics, raw pressure
units, device-side timing, or device-side missing-frame counts. No clinical,
calibration, or device transmission-completeness claim is made.

## Commits

- Parser foundation: `7468e749ecfc4d61075fcef6573b855046973b91`
- Observed compact profile / column-major mapping: `1ee5ed7`, `c12eefe`, `503e535`
- Local structural-capture record: `bb1b1fe`
- Current audit reconciliation: pending
