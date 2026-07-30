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

This historical strict-policy conclusion is superseded by the later current-policy continuity run
below. The earlier 30-minute requirement has been superseded by the confirmed 10-minute P1
acceptance; manual/operator failure scenarios still prevent a Done state.

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
the replacement policy. The replacement-policy real-device run is recorded below; cable/power/
disk/operator checks remain.

Automatic regression for the replacement policy verifies: (1) one and two consecutive bad tails
between valid frames do not invalidate; (2) the raw committed manifest counts only real frames;
(3) the encrypted derived observation contains the reconstructed frame, its flags and the
communication audit; and (4) both an empty read and a late non-empty read after five seconds
remain invalid. Automated evidence is not real-device evidence.

## 2026-07-23 real-device 10-minute continuity acceptance

The replacement runtime was exercised on `/dev/cu.usbserial-130` (CH340, `1A86:7523`) with a
5.139-second unloaded baseline, then a requested 600-second capture. It completed and committed
`VALID`: **12,396 real decoded raw frames**, **12 tail-error audit events**, and **12 derived-only
reconstructed frames**. The largest adjacent-successful-frame interval around any reconstruction
was **114.800167 ms**, below the 5-second invalidation limit. No length or function failures
occurred. Candidate CheckSum mismatched all real frames as expected under the observe-only profile.

After close, a new `StateStore` and `RecoveryScanner` reported `CLOSED/VALID`, one derived artifact
and no temporary recovery/quarantine/requeue action. This demonstrates the current 5-second rule,
raw-versus-derived separation, local commit and restart scan on the true device. Sanitized result:
[`real-device-runtime-continuity-10m-20260723.json`](real-device-runtime-continuity-10m-20260723.json).

This is not permission to mark the issue Done: actual cable removal, disk-full, power interruption,
OS secure-storage failure, operator retest and explicit export validation remain outstanding.

### 2026-07-28 actual cable-removal acceptance

The current physical device was opened at `/dev/cu.usbserial-1130` (CH340 family) and exercised
through `scripts/run_dop4864_runtime_acceptance.py`. After a qualifying 5.140026083-second
unloaded baseline (111 decoded frames; maximum cell median count 3), the USB serial cable was
removed during the requested 60-second capture. The runtime received
`SerialException: [Errno 6] Device not configured`, returned `INVALID`, did not commit a session,
and restart recovery found no temporary recovery, quarantine, orphan segment, or formal session.

The sanitized summary is `cable-removal-runtime-20260728.json` (SHA-256
`fd77aa8d6965c83a3c9fa4b8854502664160d8f49a6b5f61fd2869c90cc0345b`). It contains no raw
matrices or key material. The candidate checksum mismatched each observed frame as expected under
the permanent observe-only policy; it was not a failure condition. The isolated output directory
contained only the sanitized summary and the test SQLite state database after the run, with no
staging or formal session artifacts.

### 2026-07-28 initial storage-exhaustion result — inconclusive

The reversible, isolated physical test had no formal SQLite records but left six temporary encrypted
segments and could not write its sanitized summary. See `storage-exhaustion-runtime-20260728.md`.
This is not enough to attribute a product cleanup failure; the runner now writes its failure summary
outside the intentionally full volume. The rerun reached 100% volume use, returned `INVALID`,
left no staging files or formal SQLite records, and is accepted as the disk-full evidence.

### 2026-07-28 actual controlled-restart recovery acceptance

The current CH340 device at `/dev/cu.usbserial-1120` ran the normal local-only hardware composition
with a 5-second unloaded baseline and a requested 180-second capture. After 22 seconds, the parent
test process sent `SIGKILL` to the active-capture child, then opened a fresh `StateStore` and ran
`RecoveryScanner`. This is a controlled host-process interruption/restart test, not a claim of an
uncontrolled power-cut test.

The child return code was `-9`; restart recovery discarded exactly one active `.staging` directory.
It did not recover/quarantine/register any temporary or sealed data, and the isolated SQLite store
contained zero formal sessions, segments and derived artifacts. This is the required safe outcome:
an interrupted in-progress capture cannot become a consumer-visible session.

The recovery scanner now calls the existing `ValidSessionStager.discard_interrupted_staging(...)`
startup operation before reconciling promoted valid sessions. Automated regression plus the real
device run verify this boundary. Sanitized evidence:
[`controlled-restart-recovery-20260728.json`](controlled-restart-recovery-20260728.json), SHA-256
`55b74aa816dcb95a1e6076cc87916e40bf879d7c3dbff2659b9595ed50fc0a11`.

Known-load repeatability/position coverage is intentionally excluded from this software-functional
pass: it is manufacturer whole-device calibration work. The four-stage replay fixture remains
replay/regression evidence; a live UI-to-hardware composition is separate scope.

## 2026-07-29 current-code regression

The currently checked-out hardware composition was rerun without modifying any source files:

```text
./scripts/local-env.sh python -m pytest tests/device tests/spool tests/hardware_standardization -q
```

Result: **141 passed in 1.87s**. This covers the parser/transport, five-second valid-signal
continuity and derived-only reconstruction, invalid-session cleanup, encrypted valid-session
commit and recovery, defect repair/masks, and public physical-session export. It is automated
evidence only; the already recorded real-device 10-minute, cable-removal, disk-full and controlled
restart records above remain the physical-device evidence.

The hardware-owned acceptance is implemented. RAY-86 remains `In Review` because the last checklist
item is a software/UI-layer manual consumption test of `HardwareUiFailure`; the hardware contract
and automated mappings are present, but that UI acceptance is not claimed here.

## Commit

Automated acceptance evidence commit: pending.

## 2026-07-29 renewed local hardware acceptance

With `/dev/cu.usbserial-1140` available, the existing production-composition
acceptance script completed a local 5-second empty-board baseline followed by a
600-second capture, valid-session commit and fresh recovery scan. The result
was `COMPLETED` / `VALID` / committed with 12,404 real decoded frames. Five
tail-failure candidates were retained as audit events and reconstructed only in
the derived stream; the largest neighboring-valid gap was 112.671125 ms, below
the 5-second invalidation threshold. Candidate CheckSum mismatched all observed
frames and remained observe-only.

The post-restart store reported `CLOSED` / `VALID`, one derived artifact, and
no temporary recovery, quarantine, orphan registration, requeue or interrupted
staging action. Sanitized details are in
[`2026-07-29-runtime-acceptance.md`](2026-07-29-runtime-acceptance.md). This
adds real-device evidence; RAY-86 still requires an operator-visible UI
consumption check of `HardwareUiFailure` before it can be marked Done.
