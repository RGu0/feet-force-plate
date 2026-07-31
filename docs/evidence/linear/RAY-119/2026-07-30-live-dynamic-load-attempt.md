# RAY-119 — 真机动态加载运行时尝试（不作物理坏点结论）

- Issue: `RAY-119` — 动态坏点掩码、修复与设备健康门控
- Milestone: `P1：可靠采集`
- Captured: 2026-07-30
- Issue status at start: `In Progress`

## Preconditions and isolation

`/dev/cu.usbserial-1140` was enumerated with no process reported by `lsof` before
the capture. The device was opened only by the local capture command. All raw
bytes, temporary mask files and SQLite health audit stayed below
`/private/tmp/feetforceplate-ray119-live-20260730/`; none were committed or
copied into this evidence.

The dynamic-mask processing used the explicit validation-only ID
`ray119-validation-ch340-1a86-7523-unbound`. This is **not** a claim that a
serial-port path is a stable physical device identifier. Product UI selection
and selected-ID-to-physical-device binding were not exercised.

## Capture result

Three local-only windows were captured through the current observed compact
parser profile (3,079-byte `uint8`, 48×64 column-major; CheckSum observe-only):

| Window | Duration | Decoded frames | Disconnect | Dynamic threshold | Mask result |
| --- | ---: | ---: | --- | --- | --- |
| session-1 | 30.108 s | 622 | no | not reached | v0 → v0; 0 candidates |
| session-2 | 30.104 s | 622 | no | not reached | v0 → v0; 0 candidates |
| session-3 | 60.189 s | 1,244 | no | not reached | v0 → v0; 0 candidates |
| session-4 | 60.027 s | 1,240 | no | reached | v0 → v1; 1,949 SUSPECT candidates |

Each capture had zero invalid parsed frames. The observed CheckSum mismatched
all decoded candidates and remained an audit-only condition. The first two
captures had one parser resynchronization each; the third had one. These
transport observations are not treated as device-side lost-frame claims.

The first three windows did not meet the policy minimum and correctly produced
no candidate, no mask-version increment and no health-audit event. The fourth
window did meet the threshold, loaded the frozen v0 snapshot and atomically
persisted v1. Its 1,949 candidates were all `SUSPECT`, so no derived repair or
health block occurred; the SQLite audit contained one `MASK_UPDATED` event and
no raw frame or participant data.

This confirms that the true device stream exercises the per-device mask
load/freeze/update/audit path. It does **not** establish that those 1,949
candidate locations are physical defects: raw-value/load semantics for the
observed compact profile remain unverified, and a broad candidate set must not
be converted into a device-health conclusion. `READY` in this isolated mask
means only that the policy did not block a session; it does **not** prove the
physical board is defect-free.

## Automated regression

```text
bash scripts/local-env.sh python -m pytest tests/hardware_standardization/test_dynamic_defect_mask.py tests/hardware_standardization/test_quality_gate.py tests/device tests/spool tests/hardware_standardization -q
```

Result: **148 passed in 1.48s**.

## Acceptance boundary

This attempt is intentionally recorded with its limits. It demonstrates the
runtime mechanics on true bytes but does not close physical bad-point-detection
acceptance without confirmed raw-value semantics and a controlled load fixture.
It also does not close UI device selection, device addition, last-device
restoration, or selected-ID-to-physical-device binding. RAY-119 must remain
`In Review`.
