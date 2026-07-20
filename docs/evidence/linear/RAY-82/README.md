# RAY-82 Evidence - DO-P4864 字节级模拟器与故障注入

- URL: https://linear.app/ray-app/issue/RAY-82/do-p4864-字节级模拟器与故障注入
- Captured at: 2026-07-20T08:57:11Z
- Snapshot: Backlog; P1：可靠采集; High

## Acceptance snapshot

- [x] 48x64 / 6151-byte protocol-byte output and complement CheckSum
- [x] 1 Mbps/about 12 Hz with controlled jitter
- [x] static/load-bias/COP-sway and caller-provided distributions
- [x] partial/sticky/noise/bad-length/bad-checksum/bad-tail/disconnect injection
- [x] digest-checked raw-byte capture replay transport
- [x] no invented handshake, sampling control, device sequence, or clock
- [x] simulator and replay use the same ByteTransport/parser contracts
- [ ] physical raw capture replay through segmentation/recovery/upload contracts

## Implementation and decisions

Implemented files:

- `client/device/transport.py`: shared `ByteTransport` and disconnect error.
- `client/device/simulator.py`: 12-bit frame encoder, deterministic pressure scenes, paced synthetic transport, fault plan, and digest-checked replay.
- `tests/device/test_simulator.py`: byte-level contract and fault tests.

Generated frames require an explicit profile and traverse the RAY-81 decoder.
Synthetic profiles remain visibly unverified. Pressure scenes generate raw counts
only and do not claim calibrated units.

## Verification

Focused command:

```text
/Users/ruiguo/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -W error -m unittest tests/device/test_simulator.py
```

Fresh results:

- focused simulator: 8 tests passed in 0.023 s with warnings as errors;
- owned discovery: 19 tests passed in 0.027 s with warnings as errors;
- `compileall -q client/device tests/device`: exit 0.

See `verification.txt`.

## Boundary, failures, and limits

The replay implementation is tested with synthetic raw bytes and a verified
SHA-256. No physical serial capture exists, so real-device replay and the
downstream segmentation/recovery/upload contract cannot be accepted yet.

## Commit

Implementation and initial evidence: `1abbc1f1f01d71713b16539a80b65af7b87f8c10`.
