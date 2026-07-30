# RAY-81 Evidence - DO-P4864 协议解析与接收完整性审计

- URL: https://linear.app/ray-app/issue/RAY-81/do-p4864-协议解析与接收完整性审计
- Captured at: 2026-07-30T04:00:00Z
- Snapshot: In Review; P0：硬件基线; High
- Protocol boundary: capture-backed 3,079-byte compact `uint8` stream

## Acceptance snapshot

- [x] Supports byte-wise, random-chunked, partial, sticky, and consecutive frames.
- [x] Hard-validates header, big-endian `0x0C07` length (3,079), function code, and tail.
- [x] Records CheckSum observations and mismatches without dropping an otherwise structural frame.
- [x] Resynchronizes to the next header without clearing the full buffer, with a bounded retained buffer.
- [x] Audits received bytes, valid/invalid frames, length and CheckSum observations/mismatches, resynchronizations, discarded bytes, peak buffer, and host frame intervals.
- [x] Uses a deterministic synthetic golden wire fixture, fault injection, and seeded fuzz recovery.
- [x] Uses the capture-backed profile without unverified protocol markers; CheckSum remains explicitly audit-only.
- [x] Uses the local physical capture baseline for frame-boundary integrity.

## Implementation and decisions

`client/device/protocol.py` is the only byte-stream decoder. Its default
observed profile accepts a structural 3,079-byte frame:

```text
FF AA | 0C 07 length | 01 | 3,072-byte raw content | CheckSum candidate | FA
uint8(frame[5:3077]).reshape((48, 64), order="F")
```

The historical 6,151-byte/12-bit interface is not exposed by this runtime.
The frame header, big-endian `0x0C07` length, function code, and tail are
structural rejection criteria. CheckSum is counted as an audit observation only:
the actual compact stream does not match the historical formula, so a mismatch
marks the decoded frame but does not discard it. The profile embeds the SHA-256
of the physical-capture baseline.

Parser matrices and transport statistics remain hardware-layer data. They are
not a direct algorithm input and, because the device exposes neither a sequence
number nor a clock, they support only host-side receive-quality observation.

## Verification

Executed with the repository wrapper on macOS / Python 3.11.15:

```text
QT_QPA_PLATFORM=offscreen ./scripts/local-env.sh python -m pytest \
  --junitxml=docs/evidence/linear/RAY-81/pytest-parser-audit-regression.xml \
  tests/device/test_protocol.py tests/device/test_simulator.py \
  tests/device/test_acquisition.py \
  tests/startup_validation/test_serial_connector.py \
  tests/startup_validation/test_models_and_rules.py \
  tests/hardware_standardization/test_do_p4864_adapter.py
# 48 passed

QT_QPA_PLATFORM=offscreen ./scripts/local-env.sh ruff check \
  client/device/protocol.py client/startup_validation/serial_connector.py \
  scripts/build_dop4864_reference_fixture.py \
  scripts/render_dop4864_grid_mapping.py \
  scripts/run_dop4864_parser_capture.py \
  scripts/run_dop4864_runtime_acceptance.py \
  scripts/run_dop4864_live_display_validation.py \
  scripts/analyze_force_calibration_capture.py \
  tests/device/test_protocol.py tests/startup_validation/test_serial_connector.py \
  tests/startup_validation/test_models_and_rules.py \
  tests/hardware_standardization/test_do_p4864_adapter.py
# All checks passed

QT_QPA_PLATFORM=offscreen ./scripts/local-env.sh mypy
# Success: no issues found in 10 source files
```

The regression includes single-byte delivery, arbitrary chunk sizes, sticky
frames, leading noise, corrupt candidates, next-header recovery, bounded
buffers, simulator faults, deterministic fuzz recovery of 40 frames, and
length-mismatch rejection followed by recovery at the next valid header.

## Historical structural capture

A read-only 60-second serial capture was previously recorded locally in commit
`bb1b1fe`: 3,835,531 raw bytes (local-only SHA-256
`1d91bdd071f667481d76b4eb54a75f675a3a8b177505e0f114657402c90d9cc9`),
1,245 decoded frames, zero invalid frames, zero resynchronizations, and 1,245
candidate CheckSum mismatches. It is the runtime frame-boundary baseline; raw
bytes are intentionally not committed.

## Boundary and remaining review

The local acceptance is complete against the actual-capture baseline. Linear
will remain **In Review** until its external state is separately updated.
CheckSum coverage, raw pressure units, device-side timing, and device-side
missing-frame counts are distinct limits; they do not invalidate the confirmed
frame boundary. No clinical or calibration claim is made.

## Commits

- Parser foundation: `7468e749ecfc4d61075fcef6573b855046973b91`
- Observed compact profile / column-major mapping: `1ee5ed7`, `c12eefe`, `503e535`
- Local structural-capture record: `bb1b1fe`
- Current capture-backed integrity reconciliation: this implementation change
