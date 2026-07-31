# RAY-86 / P1 30-minute real-device runtime acceptance — 2026-07-30

## Scope

This is the P1 milestone's independent 30-minute real-device acceptance run.
It uses the production local hardware composition, not a parser recorder:

```text
5-second unloaded baseline
→ HardwareSessionRuntime acquisition
→ quality gate and encrypted valid-session commit
→ fresh StateStore + RecoveryScanner
```

The device stayed connected and the board remained unloaded.  No data was
uploaded.  Raw/derived encrypted segments and the acceptance-only AES key stay
under `/private/tmp`; this repository contains only this aggregate evidence.

## Command

```text
bash scripts/local-env.sh python scripts/run_dop4864_runtime_acceptance.py \
  --device <connected CH340 port> \
  --output-root /private/tmp/feetforceplate-p1-30m-20260730 \
  --key-file /private/tmp/feetforceplate-p1-30m-20260730.aes256 \
  --baseline-seconds 5 \
  --capture-seconds 1800 \
  --summary-output /private/tmp/feetforceplate-p1-30m-20260730-summary.json
```

## Sanitized result

* Requested baseline / continuous capture: **5 s / 1,800 s**.
* Baseline: 111 decoded frames over 5.15632375 s; maximum cell median count
  3.0; no invalid frames; one resynchronization; all candidate checksums were
  observed as mismatches and remained non-gating.
* Runtime: `COMPLETED`, `VALID`, committed; **37,183** real decoded raw frames.
* Communication audit: 41 isolated tail candidates / resynchronizations, 41
  derived-only reconstructed frames, no length or function failures.  The
  largest adjacent-valid signal gap was **113.001 ms**, below the fixed
  5-second invalidation threshold.
* Candidate checksum mismatched all 37,183 real frames.  This is expected for
  the observed compact profile and was audited, not used as a drop condition.
* Fresh-process recovery: formal session `CLOSED` / `VALID`, one derived
  artifact, and zero temporary recovery, quarantine, orphan registration,
  requeue or interrupted-staging actions.

The local sanitized summary SHA-256 was
`6fbac717fdae793d698bf8fc8dc55fa005bced4e9173b04377622f089aeb32ec`.

## Boundary

This proves the requested P1 30-minute reliable-acquisition path under the
current observed DO-P4864 profile.  It does not establish physical calibration,
clinical validity, a vendor checksum formula, per-device hardware identity, or
physical defect proof.
