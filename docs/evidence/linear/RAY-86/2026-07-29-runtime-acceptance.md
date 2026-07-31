# RAY-86 — 2026-07-29 DO-P4864 runtime acceptance

## Scope

Local-only production hardware composition on `/dev/cu.usbserial-1140` (CH340
family): qualifying empty-board baseline, 600-second capture, whole-session
quality gate, encrypted valid-session commit, and a fresh recovery scan. The
run did not upload data. Its raw and derived encrypted artifacts remain only in
the isolated `/private/tmp` output root; this repository record contains no raw
matrix values or key material.

## Sanitized result

The acceptance script requested a 5-second baseline and a 600-second capture.
It returned `COMPLETED`, `VALID`, and `committed: true`.

| Observation | Result |
| --- | --- |
| Empty-board baseline | 111 decoded frames over 5.139152292 s; maximum cell median 2.0 |
| Accepted real decoded frames | 12,404 |
| Invalid parser candidates | 5 tail failures; 0 length and 0 function failures |
| Short-fault handling | 5 derived-only reconstructions; maximum adjacent-valid gap 112.671125 ms |
| Valid-signal policy | 5,000 ms maximum; no policy violation |
| Candidate CheckSum | 12,404 observations/mismatches; observe-only, not a drop condition |
| Post-restart status | `CLOSED` / `VALID`, one derived artifact |
| Recovery scan | no temporary recovery, quarantine, orphan registration, requeue, or interrupted staging discard |

The five tail failures remained distinct protocol-integrity audit events. Their
neighboring valid frames allowed derived-only interpolation; raw encrypted
segments were not rewritten. The source summary identified itself as
`do-p4864-runtime-acceptance-result/1` and was generated at
`2026-07-30T03:24:51Z` (UTC).

## Boundary

This confirms the stated local hardware/runtime boundary only. It does not
validate calibrated force, dynamic defect-mask behavior, a physical power cut,
or an operator-visible UI recovery flow.
