# RAY-82 Evidence - DO-P4864 字节级模拟器与故障注入

- URL: https://linear.app/ray-app/issue/RAY-82/do-p4864-字节级模拟器与故障注入
- Captured at: 2026-07-23T04:45:50Z
- Snapshot: In Progress; P1：可靠采集; High

## Acceptance snapshot

- [x] 48x64 / 3079-byte uint8 column-major protocol-byte output; CheckSum behavior remains profile-controlled
- [x] 1 Mbps / configurable frame rate with controlled jitter and injected long interval
- [x] static/load-bias/COP-sway and caller-provided distributions
- [x] partial/sticky/noise/bad-length/bad-checksum/bad-tail/long-interval/disconnect injection
- [x] end-to-end bad-tail, disconnect and host-long-interval faults produce `INVALID`, discard staged data and create no formal session
- [x] bounded durable queue timeout produces `INVALID` rather than a silent drop
- [x] digest-checked raw-byte capture replay transport
- [x] no invented handshake, sampling control, device sequence, or clock
- [x] simulator and replay use the same ByteTransport/parser contracts
- [ ] physical raw capture replay through segmentation/recovery/upload contracts

## Implementation and decisions

Implemented files:

- `client/device/transport.py`: shared `ByteTransport` and disconnect error.
- `client/device/simulator.py`: observed-profile-compatible 3079-byte uint8 encoder,
  deterministic pressure scenes, paced synthetic transport, fault plan (including long
  interval), and digest-checked replay.
- `tests/device/test_simulator.py`: byte-level contract and transport-fault tests.
- `tests/device/test_runtime_fault_injection.py`: real `ByteTransport → parser →
  HardwareSessionRuntime → ValidSessionStager` tests proving structural failure,
  disconnect and host-gap invalidation remove staged data and produce no SQLite session.
- `tests/device/test_acquisition.py`: queue-full timeout is an explicit storage handoff
  failure and therefore invalidates the current capture.

Generated frames require an explicit profile and traverse the RAY-81 decoder.
Synthetic profiles remain visibly unverified. Pressure scenes generate raw counts
only and do not claim calibrated units.

## Verification

Focused command:

```text
./scripts/local-env.sh python -m pytest tests/device/test_simulator.py tests/device/test_runtime_fault_injection.py tests/device/test_acquisition.py -q
```

Fresh results:

- focused simulator/fault path: 21 passed;
- no raw test capture, network upload or UI/report path was invoked.

See `verification.txt`.

## Boundary, failures, and limits

The replay implementation is tested with synthetic raw bytes and a verified SHA-256.
No redacted physical serial capture is committed in this evidence directory, so
real-device replay, true serial timing, and downstream network transmission cannot be
accepted yet. CheckSum mismatch is explicitly **observe-only** for the current observed
compact profile; the synthetic profile's strict CheckSum tests do not change that policy.

## Commit

Implementation and initial evidence: `1abbc1f1f01d71713b16539a80b65af7b87f8c10`.

Current follow-up implementation/evidence commit: pending.
