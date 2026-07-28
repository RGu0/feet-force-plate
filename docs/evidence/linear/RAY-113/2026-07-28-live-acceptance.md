# RAY-113 — 2026-07-28 真机验收补充

- Issue: [RAY-113](https://linear.app/ray-app/issue/RAY-113/5-秒空载数据采集与传感器基线校验)
- Captured: 2026-07-28, America/Los_Angeles
- Device: DO-P4864 via CH340, opaque ref `ch340-d7a925307d7adfc00a2f`
- Scope: startup validation only; no device write command, no raw matrix persisted,
  no subject/session/report created.

## Rule adjustment driven by the device observation

The initial real empty-board run completed a 5.03-second, 105-frame window at
20.677 Hz but failed `NO_VARIATION`. A separate in-memory aggregate of a
5.2-second empty-board observation showed 12 of 3,072 cells changed (0.39%),
with counts 0–3 and a 95th-percentile temporal range of 0. Thus the previous
rule, which failed when more than 99.5% of cells were unchanged, treated a
normally stable empty board as a completely static byte stream.

`startup-baseline/2` and `startup-baseline-thresholds/2` now reject only a
window with zero changing sensor cells. Fixed nonzero regions, local anomalies,
saturation, noise, drift, receive-rate and host-gap checks remain active.
Implementation commit: `80283de` (`Tune startup validation for stable empty boards`).

## Automated verification

```text
./scripts/local-env.sh python -m pytest \
  tests/startup_validation tests/device/test_protocol.py \
  tests/device/test_simulator.py tests/device/test_acquisition.py -q
```

Result: `70 passed in 0.28s`.

The startup-validation tests cover normal pass, empty load, disconnect, stream
stall, fresh retry, receive-rate/gap, fixed values, saturation, no variation,
local anomaly, noise, drift, persistence/telemetry queue, and failure recovery.
`python -m compileall` on the changed rule and test plus `git diff --check`
also passed through the project UV wrapper.

## Real-device acceptance

| Scenario | Evidence | Result |
|---|---|---|
| Empty-board startup ×3 | Each independently opened connection completed 5.029–5.030 s, 105 frames, 20.679 Hz; each fresh parser began at `source_index=0`. | PASS ×3 |
| Empty-board after rule revision | Run `8b9b2122-a3f6-44ab-90c4-72caee420377`: 5.030 s, 105 frames, 20.677 Hz, maximum host interval 49.23 ms, 0 invalid candidates. | PASS |
| Applied hand/load | Run `ae4832c7-fe3c-4824-a9b2-ef20684c671d`: first valid frame returned `LOAD_NOT_EMPTY` / `E-DEV-103`; one frame only, partial window discarded. | RETRYABLE_FAIL as required |
| Mid-window cable disconnect | Run `b55c2025-f4cf-4b70-afc1-db2c0559333b`: after 141 valid frames over 6.771 s, returned `STREAM_INTERRUPTED` / `E-ACQ-104`; partial window discarded. | RETRYABLE_FAIL as required |
| Reconnect and new window | Run `5b12c06b-ac10-46d0-8a14-10ae903d728d`, linked to the interrupted run: 5.030 s, 105 frames, 20.677 Hz, `source_index=0`. | PASS; no prior frames reused |

The human actions were: place load, remove load, unplug during the announced
active window, then reconnect. Device enumeration immediately after an early
pre-window unplug correctly returned `DEVICE_NOT_FOUND`; it is not counted as
the mid-window result above.

## Boundaries

- This proves the observed compact 48×64 `uint8` receive/validation path on
  this device, not a physical-pressure or force calibration.
- The protocol profile remains `observed_compact_8bit` with CheckSum in
  observation mode; no claim is made that checksum coverage or raw count units
  are confirmed.
- The test establishes one device's real behavior, not cross-device, thermal,
  aging, Windows-target or long-duration threshold validation.
- Validation summaries and telemetry queue behavior are automatically tested;
  no cloud upload was attempted during the real-device commands.
