# RAY-82 Evidence - DO-P4864 字节级模拟器与故障注入

- URL: https://linear.app/ray-app/issue/RAY-82/do-p4864-字节级模拟器与故障注入
- Captured at: 2026-07-30T07:43:00Z
- Snapshot: In Progress → Done; P1：可靠采集; High

## Acceptance snapshot

- [x] 48x64 / 3079-byte uint8 column-major protocol-byte output; CheckSum behavior remains profile-controlled
- [x] 1 Mbps / configurable frame rate with controlled jitter and injected long interval; default is current observed 20.7 Hz
- [x] static/load-bias/COP-sway and caller-provided distributions
- [x] partial/sticky/noise/bad-length/bad-checksum/bad-tail/long-interval/disconnect injection
- [x] end-to-end bad-tail, disconnect and host-long-interval faults produce `INVALID`, discard staged data and create no formal session
- [x] bounded durable queue timeout produces `INVALID` rather than a silent drop
- [x] digest-checked raw-byte capture replay transport
- [x] no invented handshake, sampling control, device sequence, or clock
- [x] simulator and replay use the same ByteTransport/parser contracts
- [x] digest-checked real serial raw-byte replay through the production replay transport and observed parser; CheckSum remains OBSERVE-only

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
bash scripts/local-env.sh python -m pytest tests/device/test_protocol.py tests/device/test_simulator.py tests/device/test_runtime_fault_injection.py tests/device/test_acquisition.py -q
```

Fresh results:

- focused parser/simulator/fault path: **38 passed in 0.18s**;
- `ruff check client/device/simulator.py tests/device/test_simulator.py` and
  `git diff --check` passed;
- no network upload, UI or report path was invoked.

## 2026-07-30 connected-device capture replay

The local-only 60-second capture from the connected `/dev/cu.usbserial-1140`
device was replayed from `/private/tmp` using `CaptureReplayTransport` and a
SHA-256 verification before it entered `DaoOneP4864Parser`. No raw bytes,
matrix values, participant details or serial capture were copied into this
repository evidence.

Aggregate result: 1,240 decoded `uint8` 48×64 frames; zero invalid frames;
one resynchronization; 1,240 `CHECKSUM_NOT_ENFORCED` flags; 1,231 observed
CheckSum mismatches; and 3,072 bytes left buffered at end because the capture
ended before the next complete candidate frame. The mismatch did not discard a
frame, as required by the observed compact profile. This is parser/replay
evidence, not a claim about physical force semantics, device timestamps,
calibration, a customer test, or upload behavior.

`SyntheticP4864Transport` now defaults to 20.7 Hz—the observed compact-profile
baseline—not the historical 12 Hz. Its rate remains explicitly configurable;
this does not claim a device capability limit or create a device-side clock.

See `verification.txt`.

## Boundary, failures, and limits

The replay implementation is tested with synthetic and local-only real raw bytes
with a verified SHA-256. No physical serial capture is committed. True serial
timing is captured only by the live capture tool, while replay intentionally
does not recreate arrival timing. Network upload is outside this issue. CheckSum
mismatch is explicitly **observe-only** for the current observed compact profile;
the synthetic profile's strict CheckSum tests do not change that policy.

## Commit

Implementation and initial evidence: `1abbc1f1f01d71713b16539a80b65af7b87f8c10`.

Observed-rate follow-up implementation: `c788a3d` (`Align simulator with observed
capture rate`). This evidence update records its replay result and commit SHA.
