# RAY-86 Evidence - 可靠采集监控与 P1 验收

- URL: https://linear.app/ray-app/issue/RAY-86/可靠采集监控与-p1-验收
- Captured at: 2026-07-23T04:54:28Z
- Snapshot: In Progress; P1：可靠采集; Urgent

## Acceptance snapshot

- [x] Disconnect, storage failure and continuous five-second loss of valid decoded signal produce `INVALID` and delete the active staging directory; a single structural error/resynchronization is audited rather than invalidating the whole session.
- [x] Automated quality gate covers no bad point, one/two isolated repaired bad points, adjacent clusters, edge cells, excess baseline-noisy cells and saturation/conversion failure.
- [x] `INVALID` capture has no formal SQLite session, network handoff, derived artifact or report/algorithm input.
- [x] CheckSum remains observe-only for the observed compact profile; no device-side sequence/timestamp claim is made.
- [ ] Real 10-minute continuous run through baseline → preprocessing → valid commit → startup recovery → export.
- [ ] Actual cable removal, disk-full, power interruption, OS secure-storage and operator re-test workflow.

## Implementation and decisions

The acceptance composition is `HardwareSessionRuntime`: `ByteTransport → incremental parser →
encrypted staging → hardware quality gate → formal valid session`. Quality policy and baseline/
force provenance are recorded in the encrypted derived artifact. The parser's source index and
timestamps are host-generated; the hardware does not provide device sequence or clock data.

`scripts/run_dop4864_runtime_acceptance.py` is the operator-facing local-only P1 tool. It captures
at least five seconds of an unloaded baseline, then uses the same runtime to collect a
host-monotonic-time-bounded session, run preprocessing/quality, encrypt/commit it and reopen the
state store for recovery verification. It never writes raw matrices or key bytes to its JSON
summary. The tool has not yet been exercised against the currently detected real device.

Before the first frame, `HardwareSessionRuntime` freezes the protocol profile, device/geometry,
baseline, bad-point and force-conversion versions plus the fixed five-second valid-signal,
reconstruction and storage-timeout policies into every immutable segment and session manifest.
This makes a later replay independent of changed process defaults.

The same runtime converts exceptions from quality evaluation, encrypted derived-artifact writing or
valid-session finalization into an invalid capture. It deletes the staging directory and does not
create a SQLite session, network handoff or algorithm input; a focused regression injects a
simulated disk-full finalization failure.

## Verification

Automated command run on 2026-07-23:

```text
./scripts/local-env.sh python -m pytest tests/device tests/spool tests/hardware_standardization -q
```

Superseding automated run for the current continuity policy:

```text
./scripts/local-env.sh python -m pytest tests/device tests/spool tests/hardware_standardization -q
```

Result: **113 passed**. `git diff --check` also passed.

The full project suite after this change reported **267 passed, 2 failed**. Both failures are
pre-existing startup-validation persistence assertions that expect SQLite `schema_version == 2`
while the current shared `StateStore` reports schema version 5; this RAY-86 change does not modify
`client/spool/state_store.py` or those tests.

Existing real-device evidence under `docs/evidence/linear/RAY-78/` proves an observed 10-minute
raw structural capture at about 20.6 Hz, but it predates this validity-gated runtime and therefore
is not P1 end-to-end acceptance evidence.

## 2026-07-23 crash-window regression

The valid-session path now has an automated restart test for the post-promotion/pre-SQLite
window. A simulated process loss leaves no consumer-visible formal session until `RecoveryScanner`
validates the promoted files and completes exactly one SQLite registration. This strengthens
automatic P1 fault coverage but does not replace the required real 10-minute and cable/power/disk
acceptance run.

## Boundary, failures, and limits

### 2026-07-23 real-device result: P1 failed safely

The connected `1A86:7523` DO-P4864 was exercised through the current runtime after a qualifying
empty-board baseline. Two requested 10-minute attempts became `INVALID` after 341 and 216 frames;
a subsequent 60-second complete-runtime attempt became `INVALID` after 801 frames. The latter
recorded one tail failure and one parser resynchronization. In every attempt the temporary staging
data was removed; SQLite contains no formal session, handoff or derived observation.

A separate 60.007-second single-frame-read diagnostic decoded 1,241 frames with no structural
failure (arrival P50/P95/P99: 48.36/48.62/49.47 ms). It demonstrates that the failure is
intermittent rather than a permanent parser mismatch, but does **not** satisfy the P1 requirement:
the whole runtime must complete ten continuous clean minutes. Sanitized evidence is
[`real-device-runtime-attempts-20260723.json`](real-device-runtime-attempts-20260723.json).

The required real 10-minute and manual/operator checks cannot be marked complete without a clean
run and investigation of the intermittent structural fault. The earlier 30-minute requirement has
been superseded by the confirmed 10-minute P1 acceptance, but neither duration authorizes a Done
state until the current runtime is exercised successfully.

### 2026-07-23 10-minute communication stability observation

The operator requested a non-gating, parser-observation run to quantify the physical link. With
the same 3,079-byte single-frame read size used by the runtime, 600.005 seconds produced 12,370
decoded frames (**20.62 Hz**) and normal arrival P50/P95/P99 of **48.36/48.62/50.38 ms**. However,
there were 36 invalid structural candidates (0.290%), 37 resynchronizations, 104,594 discarded
bytes (about 33.97 frame-equivalents), and a 492.07 ms maximum host interval. The candidate
CheckSum mismatched all frames as expected under its unresolved observe-only rule and is not
counted as a structural failure. Full sanitized metrics:
[`communication-stability-10m-20260723.json`](communication-stability-10m-20260723.json).

This confirms that normal cadence is good but structural errors must remain visible to the
operator and in evidence. It does not replace an end-to-end P1 run under the current policy.

## 2026-07-22 superseding valid-signal continuity policy

The operator changed the session rule after the historical strict-runtime attempts above: a single
invalid wire candidate, noise region or parser resynchronization must **not** discard the entire
session. The current runtime records an ordered integrity event and, only when both adjacent
successful frames exist, creates an explicitly flagged derived-only interpolation of the missing
matrix. The AES-GCM raw segments retain only successful real decoded frames.

The session becomes `INVALID` if the serial transport disconnects, durable storage fails, quality
gate fails, or **5 continuous seconds** pass without a successfully decoded frame. Thus
the 2026-07-23 strict failures remain historical link observations, not acceptance evidence for
the replacement policy. The remaining real-device acceptance is a new ten-minute run with this
implementation, plus cable/power/disk/operator checks.

Automatic regression for the replacement policy verifies: (1) one and two consecutive bad tails
between valid frames do not invalidate; (2) the raw committed manifest counts only real frames;
(3) the encrypted derived observation contains the reconstructed frame, its flags and the
communication audit; and (4) both an empty read and a late non-empty read after five seconds
remain invalid. Automated evidence is not real-device evidence.

## Commit

Automated acceptance evidence commit: pending.
